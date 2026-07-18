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
- [x] Production deployment BUILD PHASE — done 2026-07-17 (docs/deployment.md,
      deploy/, docker-compose.prod.yml; Hetzner-EU CAX11 + orange-cloud +
      DNS-01 after the blog-handoff pricing correction). All locally testable.
- [x] SSH key — created in 1Password (item `box`, Ed25519);
      public half written to keys/box.pub (gitignored, regenerable via `op read`)
- [x] Provision + deploy — DONE 2026-07-18. LIVE at https://wine.example.com.
      Box: Hetzner cx23/Helsinki/x86 (<box-ip>) — cax11/ARM/fsn1 was
      capacity-out, took equivalent cheap-EU-4GB x86. Stack up, DNS-01 TLS,
      orange-cloud (Full-strict), restic→B2 verified. Secrets via 1Password op inject.
- [ ] the owner: create superuser(s) — `ssh deploy@<box-ip> -t "cd /opt/box &&
      docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser"`
      (strong password in 1Password; you + household). SSO evaluated & declined.
- [ ] Deploy latency check on seed data BEFORE loading real cellar (decide
      keep-EU/Helsinki vs switch-US-East while there's nothing to migrate)
- [ ] Load the real cellar straight into prod (prod becomes canonical DB); then
      run assistant_backfill_styles (~$2-4) so the taste map fills in
- [x] the owner: move example.com nameservers to Cloudflare — DONE (verified
      2026-07-17: amalia/hasslo.ns.cloudflare.com; apex orange-clouded)
- [ ] Later: prompt-cache the inventory/taste blocks if pairing/email volume grows
- [ ] Later (if wanted): auto-run dossier research after a label scan (~3-line change)
- [ ] Later (if Usage page shows email digestion dominating): per-feature model override in sommelier._parse, trial Sonnet on digest_email

## Done

- [x] Real design pass → mobile-first redesign shipped 2026-07-15 (bottom tab bar,
      cards, dark mode, PWA home-screen app, HEIC uploads)
- [x] Push to GitHub → current with origin/master as of 2026-07-16
