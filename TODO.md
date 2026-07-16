# TODO

- [ ] the owner: fill in `.env` — `ANTHROPIC_API_KEY` (AI features), `DISTRIBUTOR_IMAP_*` (email pipeline)
- [ ] the owner: create the dedicated distributor mailbox + auto-forward rule
- [ ] Run live smoke tests once the key is set: `scripts/dev/smoke_ai.py label <photo>` / `window` / `email <txt>` / `research`
- [ ] Both users: write a taste profile (My profile page) — recommendations improve noticeably with one
- [ ] Push to GitHub (branch stays `master` — the owner's preference)
- [ ] Schedule `assistant_poll_email` (Task Scheduler) once IMAP creds work
- [ ] Later: real design pass on the frontend (current CSS is deliberately minimal)
- [ ] Later: production WSGI (gunicorn/whitenoise) if the app ever leaves the LAN
- [ ] Later: prompt-cache the inventory/taste blocks if pairing/email volume grows
