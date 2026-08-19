from __future__ import annotations
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.config import load_config, validate_config
from src.adapters import ADAPTER_REGISTRY
from src.storage import (
    load_state,
    save_state,
    is_first_run,
    mark_first_run_complete,
    classify_jobs,
    mark_alerted,
    mark_cap_suppressed,
    update_last_checked,
    prune_seen_jobs,
)
from src.health import update_health, HEALTH_STALE, HEALTH_RECOVERED
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

    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return 1

    state_path = config.defaults.get("state_path", "state/seen_jobs.json")
    state = load_state(state_path)
    first_run = is_first_run(state)

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
    cap_hit = False
    summary_jobs = []
    any_company_succeeded = False
    companies_attempted = 0

    # Determine which companies to process
    companies = config.companies
    if getattr(args, "company", None):
        companies = [c for c in companies if c.get("name") == args.company]

    delay_range = config.defaults.get("request_delay_seconds", [2, 4])
    min_delay = float(delay_range[0]) if isinstance(delay_range, list) else 2.0
    max_delay = float(delay_range[1]) if isinstance(delay_range, (list, tuple)) and len(delay_range) > 1 else 4.0

    needs_browser = any(
        c.get("enabled", True) and c.get("config", {}).get("use_playwright", False)
        for c in companies
    )
    browser = BrowserClient() if needs_browser else None

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
            try:
                fetched = list(adapter.fetch())
                any_company_succeeded = True
            except Exception as e:
                logger.error(f"{cname}: fetch failed: {e}", exc_info=True)

            # Adapter health. Deliberately keyed on the pre-filter count: a healthy
            # adapter routinely returns postings that all fail the filters, and that
            # must stay silent. An adapter that raises leaves fetched empty too, so
            # this one signal covers both a crashing adapter and a silently-empty one.
            company_state = state["companies"].setdefault(
                cname, {"last_checked_at": None, "seen_jobs": {}}
            )
            verdict = update_health(
                company_state, len(fetched), datetime.now(timezone.utc), stale_after_hours
            )
            if verdict and notifier and not getattr(args, "dry_run", False):
                if verdict == HEALTH_STALE:
                    # State the observation, not a diagnosis. Verified 2026-08-19:
                    # Plaid and Oracle both return a well-formed empty result (`[]`
                    # and `{"items":[],"count":0}`) because they genuinely have no
                    # open postings — their adapters are fine. Only the silence is a
                    # fact; "broken" would be a guess, and wrong for those two.
                    sent = notifier.send_summary(
                        title="🔕 No postings",
                        description=(
                            f"**{cname}** has returned no job postings for over "
                            f"{stale_after_hours:.0f}h. Either the site has nothing "
                            f"open, or the adapter is broken — worth a look."
                        ),
                    )
                    # Only keep the flag if the notice actually landed, so a failed
                    # send retries next run instead of burning the single alert.
                    if not sent:
                        company_state["health"]["alerted"] = False
                elif verdict == HEALTH_RECOVERED:
                    notifier.send_summary(
                        title="✅ Adapter recovered",
                        description=f"**{cname}** is returning postings again.",
                    )

            # Apply filter pipeline
            source_config = company_cfg.get("config", {})
            matched = []
            filter_reasons = {}
            for job in fetched:
                filtered_job, reasons = apply_filter_pipeline(job, config.filters, source_config)
                if filtered_job is not None:
                    matched.append(filtered_job)
                filter_reasons[job.id] = reasons

            # Classify against first_seen state (also updates last_seen in-memory)
            freshness_hours = float(config.filters.get("freshness_hours", 48))
            now = datetime.now(timezone.utc)
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
                            sent = notifier.send_job_alert(job) if notifier else True
                            if sent:
                                alert_count += 1
                                alerted += 1
                                actually_alerted.append(job)
                    else:
                        cap_suppressed_jobs.append(job)
                elif summary_mode:
                    summary_jobs.append(job)

            # Persist first_seen state (always) and alert status (only when not dry-run)
            mark_alerted(actually_alerted, cname, state)
            mark_cap_suppressed(cap_suppressed_jobs, cname, state)
            update_last_checked(cname, state, now)

            if getattr(args, "verbose", False):
                print(
                    f"{cname}: fetched={len(fetched)} matched={len(matched)} "
                    f"candidates={len(alert_candidates)} alerted={alerted}"
                )

            # Polite delay between companies
            http.polite_delay(min_delay, max_delay)

    finally:
        if browser is not None:
            browser.close()

    # Summary mode: send one embed
    if summary_mode and summary_jobs and notifier and not getattr(args, "dry_run", False):
        desc_lines = [f"Found {len(summary_jobs)} new jobs on first run:"]
        for j in summary_jobs[:20]:
            desc_lines.append(f"• {j.company}: {j.title}")
        notifier.send_summary(
            title="📋 First Run Summary",
            description="\n".join(desc_lines),
        )

    if first_run and any_company_succeeded:
        mark_first_run_complete(state)

    if not getattr(args, "dry_run", False):
        try:
            save_state(state, state_path)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return 1

    # Backstop against silent death. Without this the run exits 0 even when every
    # site was unreachable, so a totally broken bot looks identical to a quiet one
    # and nobody finds out until they notice the alerts stopped.
    #
    # Deliberately narrow: it fires only when NOTHING worked. An adapter that
    # degrades gracefully to [] still counts as a success here, so this does not
    # catch a single dead adapter — per-company health reporting is that fix, and
    # it belongs on Discord rather than in a red cron that runs 96 times a day.
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

    args = parser.parse_args()
    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command == "validate-config":
        sys.exit(cmd_validate_config(args))
    elif args.command == "test-discord":
        sys.exit(cmd_test_discord(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "daemon":
        sys.exit(cmd_daemon(args))


if __name__ == "__main__":
    main()
