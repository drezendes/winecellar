# TODO

- [ ] the owner: fill in `.env` — `DISTRIBUTOR_IMAP_*` (email pipeline).
      `ANTHROPIC_API_KEY` is in place (2026-07-15, laptop).
- [ ] the owner: create the dedicated distributor mailbox + auto-forward rule
- [ ] Run live smoke tests: `scripts/dev/smoke_ai.py label <photo>` / `window` / `email <txt>`.
      (`research` verified live in-app 2026-07-15 — dossier saved for Monte Bello 2019.)
- [ ] Both users: write a taste profile (My profile page) — recommendations improve noticeably with one
- [ ] Schedule `assistant_poll_email` (Task Scheduler) once IMAP creds work
- [ ] iPhone sanity pass on the new mobile UI (Add to Home Screen, camera scan,
      dark mode) — verified headless at 390×844, not yet on the real device.
      Re-check after the 2026-07-16 "Cellar book" design pass (new fonts, gauge,
      dots — confirm woff2 loads and Marcellus renders on-device)
- [ ] Consider regenerating the PWA icons to match the new identity (current
      icons predate the design pass — scripts/dev/make_icons.py)
- [ ] Taste map — commissioned, plan at docs/taste_map_plan.md. Phase D (open
      bottles) DONE; remaining: A style vectors → B map page → C prospects
- [ ] Cellar valuation — QUEUED behind the taste map. Sketch stress-tested and
      ready to build: docs/ideas.md (actuals-only purchase price, quarterly
      "value my cellar" runs, per-vintage valuation rows, cost-basis rule)
- [x] Open-bottle state (opt-in "not finishing it" checkbox) — built 2026-07-16
- [ ] Later (sketched in docs/ideas.md): producer world map (engraved SVG atlas style)
- [ ] Later: production WSGI (gunicorn/whitenoise) if the app ever leaves the LAN
- [ ] Later: prompt-cache the inventory/taste blocks if pairing/email volume grows
- [ ] Later (if wanted): auto-run dossier research after a label scan (~3-line change)
- [ ] Later (if Usage page shows email digestion dominating): per-feature model override in sommelier._parse, trial Sonnet on digest_email

## Done

- [x] Real design pass → mobile-first redesign shipped 2026-07-15 (bottom tab bar,
      cards, dark mode, PWA home-screen app, HEIC uploads)
- [x] Push to GitHub → current with origin/master as of 2026-07-16
