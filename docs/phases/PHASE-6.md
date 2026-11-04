# Phase 6 executable contract — application tracking and improvement

STATUS PLANNED. Requires Phase 5 released. PRs P6-A/B/C. No auto-apply.

## P6-A: application/outreach event model
- Persist `JobSnapshot` and exact `ResumeArtifact` used for every application; `saved` is not `applied`. Owner explicitly records application submission, assessment, interview, offer, reject, withdrawal; event records append-only with timestamps and source.
- Link optional referral/contact/outreach; statuses from messages/recruiter portal never inferred as confirmed without owner confirmation.
- Changes atomic, idempotent and reversible via correction events; duplicate canonical jobs do not create parallel application cards.
- Private exports and deletion with retention policy and audit.

## P6-B: reminders and digest
- Daily/batched saved-job updates; user-configurable follow-up reminders for outreach and applications; no invented deadlines or message sends. Posting closure uses employer verification, not age alone.
- Scheduler may be late; reminders track due time, delivery time, dedupe key and failures; no repeated spam on retry.
- Discord commands `/applications`, `/application stage`, `/digest`, `/followups`, private access and unsubscribe controls.
- Optional Gmail read-only classification can be prototyped with consent, never a prerequisite to release.

## P6-C: feedback loop, quality dashboards, hardening
- Owner explicit save/ignore/apply/decline signals adjust rankings only within known fact/evidence boundaries.
- Monitor coverage/precision/recall, missed new-grad openings, alert noise, measured posting-to-alert time, source freshness, provider quota and actual approved sends.
- Optional consented Gmail classification marks extracted suggestions `needs_review` until verified; no auto-email, no scraped third-party contents.
- Shadow compare old/new ranking, score versioning, export, rollback; security and retention audit.

**Release:** real owner-authorized state transitions and at least one deduplicated reminder verified, full test/security gates, no application claims based solely on opening job URL.
