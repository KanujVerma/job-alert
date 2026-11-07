# P2-A implementation plan and contracts

Base inspected: `d98afe73674925f8aaeb9d6fe21df0b077375689` (727-test baseline).
Scope: public Greenhouse + Ashby read-only adapters, registry/config validation,
structured source facts, safe normalization, regression + read-only smoke tests.
Production `companies.yaml`, job-alerts workflow and state remain unchanged.

1. Add `src/adapters/public_board.py` for endpoint/config, URL, response bounds,
   HTML, date and compensation normalization. Fixed public API hosts; no login,
   arbitrary endpoint overrides, application submissions or redirects.
2. Add `GreenhouseAdapter` / `AshbyAdapter`; preserve distinct source post IDs,
   descriptions, multi-location information, nullable dates and public URLs.
   Greenhouse prospect posts and Ashby unlisted posts are not discoverable jobs.
   Neither published list contract documents pagination: do not invent cursors;
   fail if a response advertises incomplete coverage.
3. Add optional source metadata to frozen Job without breaking old constructors.
   Explicit source employment type beats title guesses; missing/incomplete
   descriptions or unknown source employment must not produce verified alerts.
4. Add configuration validation and registry imports; no new active employers.
5. Fixture tests plus normal filter/notifier/dedup/do_run integration tests.
6. Standalone read-only smoke CLI emits metadata-only JSON receipts and hashes
   production config/state before/after. No credentials, writes to state or
   webhook sends. Approved demo manifests stay outside production config.
7. Update STATUS/HANDOFF/RELEASE_LOG and precise Gemini checklist before PR.

No P2-B feed ingestion, P2-C database, AI or private candidate data.
The older Phase 1 post-merge live gate is still unverified; owner requested
implementation now, but activation/merge release gates remain explicit.
