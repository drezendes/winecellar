# TODO

- [x] **Rating scale rework** — BUILT 2026-07-30 (`docs/rating_scale_plan.md`)
- [x] **Deployed to prod 2026-07-30.** The migration converted the 5 rated
      notes; the owner's reviewed corrections (+0.5 on all but one) were
      applied straight after. Prod now reads 3.0 / 3.5 / 2.5 / 3.0 / 4.5.
- [ ] Later (if wanted): let dossier research fill `Vintage.critic_score` when
      it turns up a published score — fits the existing research-backfill rule
      (a label fact, not a taste judgement), so it may fill blanks only.
- [ ] The owner: fill in `.env` — `DISTRIBUTOR_IMAP_*` (email pipeline).
      `ANTHROPIC_API_KEY` is in place (2026-07-15, laptop).
- [ ] The owner: create the dedicated distributor mailbox + auto-forward rule
- [ ] Run live smoke tests: `scripts/dev/smoke_ai.py label <photo>` / `window` / `email <txt>`.
      (`research` verified live in-app 2026-07-15 — dossier saved for Monte Bello 2019.)
- [ ] Both users: write a taste profile (My profile page) — recommendations improve noticeably with one
- [ ] Schedule `assistant_poll_email` (Task Scheduler) once IMAP creds work
- [ ] iPhone: confirm the photo picker offers **Photo Library** on both scan
      pages after dropping `capture` (2026-07-24). If a tap ever opens *nothing*
      again, first check whether it's the home-screen (standalone) shell — open
      the same page in Safari proper to compare; iOS file inputs are flakier in
      standalone mode.
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
- [ ] Later: prompt-cache the inventory/taste blocks if pairing/email volume grows
- [ ] Later (if wanted): auto-run dossier research after a label scan (~3-line change)
- [ ] Later (if Usage page shows email digestion dominating): per-feature model override in sommelier._parse, trial Sonnet on digest_email

> Production/deploy tasks moved to the private infra repo (`infra/TODO.md`) when
> this app was demoted to a pure, identity-free tenant. The `deploy/` here is a
> standalone example (see `deploy/README.md`).

## Done

- [x] Real design pass → mobile-first redesign shipped 2026-07-15 (bottom tab bar,
      cards, dark mode, PWA home-screen app, HEIC uploads)
- [x] Push to GitHub → current with origin/master as of 2026-07-16
