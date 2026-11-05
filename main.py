from __future__ import annotations
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.config import load_config, validate_config
from src.adapters import ADAPTER_REGISTRY, browser_required
from src.storage import (
    POLICY_VERSION,
    StateCorruptionError,
    load_state,
    save_state,
    is_first_run,
    mark_first_run_complete,
    classify_jobs,
    mark_alerted,
    mark_cap_suppressed,
    update_last_checked,
    prune_seen_jobs,
    normalize_url,
    is_url_alerted,
    record_alerted_url,
    is_backfill_pending,
    mark_backfill_completed,
    get_backfill_candidates,
    record_review_job,
    remove_review_job,
    get_daily_review_digest,
)
from src.health import (
    update_health,
    HEALTH_STALE,
    HEALTH_RECOVERED,
    compute_run_diagnostics,
    record_run_heartbeat,
)
from src.http import HTTPClient
from src.browser import BrowserClient
from src.notifier import Notifier
from src.filtering import apply_filter_pipeline
from src.scheduler import run_loop


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_validate_config(args) -> int:
    load_dotenv()
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        return 1

    errors = validate_config(config, ADAPTER_REGISTRY, dry_run=True)
    if errors:
        for err in errors:
            print(f"ERROR: {err}")
        return 1
    print("Config is valid.")
    return 0


def cmd_needs_browser(args) -> int:
    """Print `true` or `false` — does this config need Chromium installed?

    stdout is a machine-readable answer consumed by the CI workflow, so it stays
    exactly one lowercase word. Diagnostics go to stderr; a config that cannot be
    loaded exits non-zero rather than printing a guess, and the workflow treats
    that as `true` so a broken probe never silently guts a scrape.
    """
    load_dotenv()
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}", file=sys.stderr)
        return 1

    print("true" if browser_required(config.companies, ADAPTER_REGISTRY) else "false")
    return 0


def cmd_test_discord(args) -> int:
    load_dotenv()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL is not set.")
        return 1

    notifier = Notifier(webhook_url)
    ok = notifier.send_summary(
        title="🧪 Job Alert Bot — Test",
        description="Webhook is working correctly. Bot is configured.",
    )
    if ok:
        print("Discord test message sent successfully.")
        return 0
    else:
        print("ERROR: Failed to send Discord test message.")
        return 1


def do_run(args) -> int:
    load_dotenv()
    logger = logging.getLogger(__name__)
    run_start = datetime.now(timezone.utc)

    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return 1

    state_path = config.defaults.get("state_path", "state/seen_jobs.json")
    try:
        state = load_state(state_path, raise_on_corrupt=True)
    except StateCorruptionError as e:
        logger.error(f"Failed to load state: {e}. Aborting run to prevent alert storm.")
        return 1

    first_run = is_first_run(state)
    is_new_policy_migration = False
    if getattr(args, "rerun_backfill", False):
        is_new_policy_migration = True
    elif not first_run and is_backfill_pending(state, POLICY_VERSION):
        is_new_policy_migration = True

    ttl_days = int(config.defaults.get("first_seen_ttl_days", 180))
    prune_seen_jobs(state, ttl_days, datetime.now(timezone.utc))

    # Determine notification mode
    notify = False
    summary_mode = False
    if first_run:
        if getattr(args, "firehose_first_run", False):
            notify = True
        elif getattr(args, "summary_first_run", False):
            summary_mode = True
        else:
            notify = False  # silent backfill
    else:
        notify = True

    # Set up notifier
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    notifier = Notifier(webhook_url) if webhook_url else None

    http = HTTPClient(
        user_agent=config.user_agent,
        timeout=15,
        max_retries=3,
    )

    max_alerts = config.defaults.get("max_alerts_per_run", 25)
    stale_after_hours = float(config.defaults.get("adapter_stale_after_hours", 24))
    alert_count = 0
    alert_failures = 0
    cap_hit = False
    summary_jobs = []
    backfill_jobs: list[Job] = []
    any_company_succeeded = False
    companies_attempted = 0
    company_stats: dict[str, dict] = {}

    alerted_urls: set[str] = set()

    # Determine which companies to process
    companies = config.companies
    if getattr(args, "company", None):
        companies = [c for c in companies if c.get("name") == args.company]

    delay_range = config.defaults.get("request_delay_seconds", [2, 4])
    min_delay = float(delay_range[0]) if isinstance(delay_range, list) else 2.0
    max_delay = float(delay_range[1]) if isinstance(delay_range, (list, tuple)) and len(delay_range) > 1 else 4.0

    browser = BrowserClient() if browser_required(companies, ADAPTER_REGISTRY) else None

    try:
        for company_cfg in companies:
            if not company_cfg.get("enabled", True):
                continue

            cname = company_cfg["name"]
            adapter_key = company_cfg.get("adapter")

            if adapter_key not in ADAPTER_REGISTRY:
                logger.debug(f"Skipping {cname}: adapter '{adapter_key}' not registered")
                continue

            adapter_cls = ADAPTER_REGISTRY[adapter_key]
            adapter = adapter_cls(cname, company_cfg.get("config", {}), http, browser=browser)

            fetched = []
            companies_attempted += 1
            fetch_error: str | None = None
            adapter_succeeded = False
            try:
                fetched = list(adapter.fetch())
                any_company_succeeded = True
                adapter_succeeded = True
            except Exception as e:
                fetch_error = str(e)
                logger.error(f"{cname}: fetch failed: {e}", exc_info=True)

            # Adapter health. Keyed on pre-filter count.
            company_state = state["companies"].setdefault(
                cname, {"last_checked_at": None, "seen_jobs": {}}
            )
            if not adapter_succeeded:
                company_state["last_error"] = fetch_error
                company_state["last_error_at"] = datetime.now(timezone.utc).isoformat()
            else:
                company_state.pop("last_error", None)
                company_state.pop("last_error_at", None)
                verdict = update_health(
                    company_state, len(fetched), datetime.now(timezone.utc), stale_after_hours
                )
                if verdict and notifier and not getattr(args, "dry_run", False):
                    if verdict == HEALTH_STALE:
                        sent = notifier.send_summary(
                            title="🝝 No postings",
                            description=(
                                f"**{cname}** has returned no job postings for over "
                                f"{stale_after_hours:.0f}h. Either the site has nothing "
                                f"open, or the adapter is broken — worth a look."
                            ),
                        )
                        if not sent:
                            company_state["health"]["alerted"] = False
                    elif verdict == HEALTH_RECOVERED:
                        notifier.send_summary(
                            title="✅ Adapter recovered",
                            description=f"**{cname}** is returning postings again.",
                        )

            # Apply filter pipeline
            source_config = company_cfg.get("config", {})
            is_network = bool(company_cfg.get("network_priority", False))
            cohort = str(company_cfg.get("cohort", "discovered"))
            referral_status = str(company_cfg.get("referral_status", "unconfirmed" if is_network else "unavailable"))

            # Keep individual alert candidate matching strictly bound to standard freshness (48h)
            # Decouple widened 7-day backfill candidate set so historical postings (48-168h) do not enter alert_candidates
            backfill_filters = None
            if is_new_policy_migration:
                backfill_filters = dict(config.filters)
                backfill_filters["freshness_hours"] = max(
                    float(config.filters.get("freshness_hours", 48)), 7 * 24.0
                )

            matched = []
            backfill_matched = []
            review_count = 0
            excluded_count = 0
            filter_reasons = {}
            loop_now = datetime.now(timezone.utc)
            for job in fetched:
                # Normal pipeline evaluation (standard 48h freshness threshold for individual alerts)
                filtered_job, reasons = apply_filter_pipeline(job, config.filters, source_config)
                if filtered_job is not None:
                    import dataclasses
                    filtered_job = dataclasses.replace(
                        filtered_job,
                        network_priority=is_network,
                        cohort=cohort,
                        referral_status=referral_status,
                    )
                    matched.append(filtered_job)
                    if backfill_filters is not None:
                        backfill_matched.append(filtered_job)
                    remove_review_job(state, job.id)
                else:
                    # If pending migration/backfill, check if eligible under widened 7-day backfill freshness
                    if backfill_filters is not None:
                        bf_job, _ = apply_filter_pipeline(job, backfill_filters, source_config)
                        if bf_job is not None:
                            import dataclasses
                            bf_job = dataclasses.replace(
                                bf_job,
                                network_priority=is_network,
                                cohort=cohort,
                                referral_status=referral_status,
                            )
                            backfill_matched.append(bf_job)
                            remove_review_job(state, job.id)

                    if any("needs_review" in r for r in reasons):
                        review_count += 1
                        import dataclasses
                        review_job = dataclasses.replace(
                            job,
                            network_priority=is_network,
                            cohort=cohort,
                            referral_status=referral_status,
                        )
                        record_review_job(state, review_job, reasons, loop_now)
                    else:
                        excluded_count += 1
                        remove_review_job(state, job.id)
                filter_reasons[job.id] = reasons

            # Record per-company stats for health reporting
            company_stats[cname] = {
                "status": "failed" if not adapter_succeeded else ("zero" if len(fetched) == 0 else "ok"),
                "error": fetch_error,
                "fetched": len(fetched),
                "matched": len(matched),
                "review": review_count,
                "excluded": excluded_count,
            }

            # Classify against first_seen state for individual alerts
            freshness_hours = float(config.filters.get("freshness_hours", 48))
            now = loop_now
            alert_candidates = classify_jobs(
                matched, cname, state, freshness_hours, now,
                verbose=getattr(args, "verbose", False),
            )

            actually_alerted: list = []
            cap_suppressed_jobs: list = []
            alerted = 0

            for job in alert_candidates:
                if notify and not getattr(args, "dry_run", False):
                    if not cap_hit:
                        if alert_count >= max_alerts:
                            cap_hit = True
                            cap_suppressed_jobs.append(job)
                            if notifier:
                                notifier.send_summary(
                                    title="⚠️ Alert Cap Reached",
                                    description=f"Max alerts per run ({max_alerts}) reached. Remaining jobs silenced.",
                                )
                        else:
                            url_key = normalize_url(job.url)
                            if url_key and (url_key in alerted_urls or is_url_alerted(job.url, state)):
                                logger.info(
                                    "%s: %r already alerted under another company or prior run (%s) — not sending twice.",
                                    cname, job.title, job.url,
                                )
                                actually_alerted.append(job)
                            else:
                                if notifier is None:
                                    logger.warning(
                                        "%s: %r alert not delivered (no DISCORD_WEBHOOK_URL set).",
                                        cname, job.title,
                                    )
                                    sent = False
                                else:
                                    try:
                                        sent = notifier.send_job_alert(job)
                                    except Exception as exc:
                                        logger.error("%s: %r alert exception: %s", cname, job.title, exc)
                                        sent = False

                                if sent:
                                    if url_key:
                                        alerted_urls.add(url_key)
                                        record_alerted_url(job.url, cname, job.id, state, now)
                                    alert_count += 1
                                    alerted += 1
                                    actually_alerted.append(job)
                                else:
                                    alert_failures += 1
                    else:
                        cap_suppressed_jobs.append(job)
                elif summary_mode:
                    summary_jobs.append(job)

            # Persist first_seen state (always) and alert status (only when not dry-run)
            mark_alerted(actually_alerted, cname, state)
            mark_cap_suppressed(cap_suppressed_jobs, cname, state)
            update_last_checked(cname, state, now)

            # Collect bounded backfill candidates if pending migration
            # Kept separate from alert_candidates: historical postings (48-168h) appear in backfill summary, not individual alerts
            if is_new_policy_migration:
                company_backfill_candidates = get_backfill_candidates(backfill_matched, state, loop_now, lookback_days=7)
                alerted_urls_this_run = {normalize_url(j.url) for j in actually_alerted}
                company_backfill_candidates = [
                    j for j in company_backfill_candidates
                    if normalize_url(j.url) not in alerted_urls_this_run
                ]
                backfill_jobs.extend(company_backfill_candidates)

            if getattr(args, "verbose", False):
                if config.filters.get("mode") == "new_grad_full_time":
                    print(
                        f"{cname}: fetched={len(fetched)} matched={len(matched)} "
                        f"review={review_count} excluded={excluded_count} "
                        f"candidates={len(alert_candidates)} alerted={alerted}"
                    )
                else:
                    print(
                        f"{cname}: fetched={len(fetched)} matched={len(matched)} "
                        f"candidates={len(alert_candidates)} alerted={alerted}"
                    )

            # Polite delay between companies
            http.polite_delay(min_delay, max_delay)

    finally:
        if browser is not None:
            browser.close()

    # Summary mode: send one embed (legacy first run)
    if summary_mode and summary_jobs and notifier and not getattr(args, "dry_run", False):
        desc_lines = [f"Found {len(summary_jobs)} new jobs on first run:"]
        for j in summary_jobs[:20]:
            desc_lines.append(f"• {j.company}: {j.title}")
        notifier.send_summary(
            title="📋 First Run Summary",
            description="\n".join(desc_lines),
        )

    # Policy backfill summary (Jobbie 2.1 migration first run or manual rerun)
    if is_new_policy_migration:
        unique_backfill: list[Job] = []
        seen_bf_urls: set[str] = set()
        for j in backfill_jobs:
            nurl = normalize_url(j.url)
            if nurl and nurl in seen_bf_urls:
                continue
            if nurl:
                seen_bf_urls.add(nurl)
            unique_backfill.append(j)

        if not getattr(args, "dry_run", False) and any_company_succeeded:
            if unique_backfill:
                if notifier:
                    total_bf = len(unique_backfill)
                    desc_lines = [
                        f"Found {total_bf} eligible jobs from the last 7 days across monitored sites (showing {min(10, total_bf)}):"
                    ]
                    for j in unique_backfill[:10]:
                        loc_str = f" ({j.location})" if j.location else ""
                        desc_lines.append(f"• [{j.company}: {j.title}]({j.url}){loc_str}")
                    try:
                        sent = notifier.send_summary(
                            title="📋 Phase 1 Policy Backfill (Last 7 Days)",
                            description="\n".join(desc_lines),
                        )
                    except Exception as exc:
                        logger.error("Failed to send backfill summary to Discord: %s", exc)
                        sent = False

                    if sent:
                        mark_backfill_completed(state, POLICY_VERSION, datetime.now(timezone.utc))
                        for j in unique_backfill:
                            mark_alerted([j], j.company, state)
                            record_alerted_url(j.url, j.company, j.id, state, datetime.now(timezone.utc))
                    else:
                        logger.warning("Backfill summary delivery failed or unconfirmed; leaving backfill pending.")
                else:
                    logger.warning("No Discord notifier configured; backfill summary cannot be delivered. Leaving backfill pending.")
            else:
                # No backfill jobs found across any monitored source; safely mark completed
                mark_backfill_completed(state, POLICY_VERSION, datetime.now(timezone.utc))
        elif getattr(args, "dry_run", False):
            print(
                f"Migration backfill preview: found {len(unique_backfill)} eligible jobs from last 7 days "
                f"(would send summary capped at 10)."
            )

    # Daily review digest
    if notifier and not getattr(args, "dry_run", False):
        digest_res = get_daily_review_digest(state, datetime.now(timezone.utc), cap=10)
        if digest_res is not None:
            review_items, total_rev = digest_res
            if review_items:
                lines = [f"Found {total_rev} positions needing review (showing up to {len(review_items)}):"]
                for item in review_items:
                    reasons_str = ", ".join(item.get("reasons", []))
                    lines.append(f"• [{item.get('company')}: {item.get('title')}]({item.get('url')}) — `{reasons_str}`")
                sent = notifier.send_summary(
                    title="📋 Daily Review Digest",
                    description="\n".join(lines),
                )
                if sent:
                    state.setdefault("review_digest", {})["last_sent_at"] = datetime.now(timezone.utc).isoformat()

    if first_run and any_company_succeeded:
        mark_first_run_complete(state)

    # Compute diagnostics and record heartbeat
    run_finish = datetime.now(timezone.utc)
    cadence_min = int(config.defaults.get("schedule_minutes", 15))
    diag = compute_run_diagnostics(
        state, run_start, run_finish, cadence_min, company_stats, alert_count, alert_failure_count=alert_failures
    )
    record_run_heartbeat(state, diag)
    gap_display = f"{diag['gap_since_last_run_seconds']}s" if diag['gap_since_last_run_seconds'] is not None else "initial"
    logger.info(
        "Run heartbeat: duration=%.2fs, gap=%s, scheduler_gap=%s, adapters=%d/%d (zero=%d), matched=%d, review=%d, excluded=%d, alerted=%d",
        diag["duration_seconds"],
        gap_display,
        diag["scheduler_gap_detected"],
        diag["adapters_succeeded"],
        diag["adapters_attempted"],
        diag["adapters_zero_results"],
        diag["accepted_count"],
        diag["review_count"],
        diag["excluded_count"],
        diag["alert_success_count"],
    )
    if diag["scheduler_gap_detected"]:
        gap_mins = diag["gap_since_last_run_seconds"] / 60.0
        logger.warning(
            "Scheduler gap detected! Elapsed since last run: %.1f minutes (expected ~%d min). Actions schedule drift observed.",
            gap_mins, cadence_min,
        )

    if not getattr(args, "dry_run", False):
        try:
            save_state(state, state_path)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return 1

    # Backstop against silent death.
    if not any_company_succeeded:
        if companies_attempted == 0:
            logger.error(
                "No companies were processed. Check the config and any --company filter."
            )
        else:
            logger.error(
                "All %d companies failed to fetch. Treating this run as failed.",
                companies_attempted,
            )
        return 1

    return 0


def cmd_run(args) -> int:
    return do_run(args)


def cmd_daemon(args) -> int:
    load_dotenv()
    try:
        config = load_config(args.config)
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to load config: {e}")
        return 1

    interval = config.defaults.get("schedule_minutes", 15)

    def run_fn():
        do_run(args)

    run_loop(run_fn, interval_minutes=interval)
    return 0  # unreachable


def main():
    parser = argparse.ArgumentParser(
        prog="job-alert",
        description="Monitor career sites for job postings and alert via Discord.",
    )
    parser.add_argument(
        "--config",
        default="companies.yaml",
        help="Path to companies YAML config (default: companies.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate-config
    subparsers.add_parser("validate-config", help="Validate the YAML config")

    # needs-browser
    subparsers.add_parser(
        "needs-browser",
        help="Print true/false: does any enabled company require a browser?",
    )

    # test-discord
    subparsers.add_parser("test-discord", help="Send a test Discord webhook message")

    # run
    run_parser = subparsers.add_parser("run", help="Run one scrape cycle")
    run_parser.add_argument("--company", help="Only process this company by name")
    run_parser.add_argument("--dry-run", action="store_true", help="Don't send alerts or save state")
    run_parser.add_argument("--verbose", action="store_true", help="Verbose output")
    run_parser.add_argument(
        "--firehose-first-run",
        action="store_true",
        help="On first run, notify all found jobs",
    )
    run_parser.add_argument(
        "--summary-first-run",
        action="store_true",
        help="On first run, send one summary embed",
    )
    run_parser.add_argument(
        "--rerun-backfill",
        action="store_true",
        help="Force re-running the 7-day migration backfill summary without resetting seen state",
    )

    # daemon
    daemon_parser = subparsers.add_parser("daemon", help="Run continuously on schedule")
    daemon_parser.add_argument("--company", help="Only process this company by name")
    daemon_parser.add_argument("--dry-run", action="store_true")
    daemon_parser.add_argument("--verbose", action="store_true")
    # These flags only take effect on the first run cycle; subsequent cycles ignore them.
    daemon_parser.add_argument(
        "--firehose-first-run",
        action="store_true",
        help="On first run, notify all found jobs",
    )
    daemon_parser.add_argument(
        "--summary-first-run",
        action="store_true",
        help="On first run, send one summary embed",
    )
    daemon_parser.add_argument(
        "--rerun-backfill",
        action="store_true",
        help="Force re-running the 7-day migration backfill summary without resetting seen state",
    )

    args = parser.parse_args()
    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command == "validate-config":
        sys.exit(cmd_validate_config(args))
    elif args.command == "needs-browser":
        sys.exit(cmd_needs_browser(args))
    elif args.command == "test-discord":
        sys.exit(cmd_test_discord(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "daemon":
        sys.exit(cmd_daemon(args))


if __name__ == "__main__":
    main()
