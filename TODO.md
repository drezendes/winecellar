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
- [x] Taste map — ALL PHASES BUILT 2026-07-16 (docs/taste_map_plan.md)
- [ ] Run `assistant_backfill_styles` after the real cellar is loaded (~$2-4
      for 200 wines) so the map fills in
- [x] Cellar valuation — BUILT 2026-07-16 (/assistant/value/; run it quarterly)
- [ ] Later: paid-vs-worth chart on the value page once a few real runs exist
      (dataviz skill; table is the honest form until then)
- [ ] Later (~2027, after their marketing campaign launches): deep-research
      Quinta de Adorigo (Douro, nr. Tabuaço) — estate sale, acquired cask
      stocks, any IVDP ultra-age certification, the 50yr tawny relaunch
      pricing. Attach findings to the owner's bottle's dossier BEFORE the
      campaign rewrites the story. Session-research → direct DB write is
      fine here (see CLAUDE.md, direct-to-DB research pattern).
- [x] Open-bottle state (opt-in "not finishing it" checkbox) — built 2026-07-16
- [ ] Later (sketched in docs/ideas.md): producer world map (engraved SVG atlas style)
- [ ] Production deployment — PLANNED, docs/deployment.md (Hetzner + Compose +
      Postgres + Caddy, Cloudflare DNS, wine.example.com). Sequence:
      the owner moves nameservers to Cloudflare (anytime, free) → build phase →
      provision → deploy → load real cellar straight into prod
- [ ] the owner: move example.com nameservers to Cloudflare (free tier; copy
      existing WP records first — blog keeps working)
- [ ] Later: prompt-cache the inventory/taste blocks if pairing/email volume grows
- [ ] Later (if wanted): auto-run dossier research after a label scan (~3-line change)
- [ ] Later (if Usage page shows email digestion dominating): per-feature model override in sommelier._parse, trial Sonnet on digest_email

## Done

- [x] Real design pass → mobile-first redesign shipped 2026-07-15 (bottom tab bar,
      cards, dark mode, PWA home-screen app, HEIC uploads)
- [x] Push to GitHub → current with origin/master as of 2026-07-16
