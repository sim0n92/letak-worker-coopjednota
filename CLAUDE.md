# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

`letak-worker-coopjednota` is a **ProcMon Process Class** (spec v1.0, type
`stdin`) that parses COOP Jednota Slovensko's leaflet list
(`https://www.coop.sk/letaky`, since 2026-10) and reports leaflets not in the
caller-supplied `knownLeaflets` list. Stateless; metadata + URLs only (no downloads).

- **Protocol contract** lives in the `ProcessMonitor` repo:
  `docs/process-class-specification-v1.md` (org `0ics-srls`).
- **Reference implementation** of the protocol wrapper: `letak-worker-billa`
  (same `ProcessClass`/`Worker.execute()` split, same test structure).

## Contract (do not break)

- stdin: one JSON line with `_action`; stays open for a later `terminate`.
- stdout: JSON Lines, **only** `{type:progress|result|error}` — never logs.
- logs: `/logs/events.log`, Serilog-style, honor `LOG_LEVEL`.
- exit: 0 success (must emit `result`), 1 error, 2 input error, 4 dependency error.
- `--version` must equal `manifest.json#version`.

## Deviation from other chains: 4-part novelty key

coop.sk is a federation of regional cooperatives. The **same banner**
(Tempo/Supermarket/CoopPotraviny) can publish **multiple distinct leaflets for
the same validity date range at once** (regional variants) — the page gives
no readable region/store label to tell them apart. Because of this:

- **Novelty key here is `type|from|to|id` (4 parts)**, not the 3-part
  `type|from|to` used by every sibling worker (kaufland/billa/tesco/lidl).
  `id` is the slug of the leaflet's page on coop.sk (`tempo-43-2026`). Until
  2026-10 it was the record id from the old PDF path (`flip_1343` → `"1343"`);
  old keys simply no longer match.
- Output leaflets therefore include an explicit `id` field:
  `{type, from, to, id, url}`.
- Anything downstream that builds `knownLeaflets` generically as
  `type|from|to` across all chains needs a coopjednota-specific branch that
  also includes `id`, or coopjednota leaflets will look "new" forever.

This was discussed and agreed with the other worker agents in the shared
`letak-worker` chat room before implementation — see `PLAN.md` for the
decision trail if it needs revisiting.

## Where to work

- Fetch + parsing lives in `src/coopjednota.py` (pure functions, unit-tested
  against `tests/fixtures/coop_{letaky,detail,viewer}.html`); the protocol
  plumbing is in `src/main.py` (`ProcessClass`); `CoopjednotaWorker.execute()`
  wires them.
- Three hops per leaflet: the list's JSON-LD (name, page URL, validity) → the
  leaflet page's Adobe InDesign iframe → the viewer's manifest
  (`documentPdf` + `VERSION_PREFIX` → the PDF URL). Only leaflets that pass the
  `types` filter and are new get the two extra fetches.
- `type` comes from the leaflet name (`banner_of`): "Potraviny, Supermarket a
  Tempo" → `CoopPotraviny`, "Tempo" → `Tempo`, regional → `Regional`.
- An empty list (`NO_LEAFLETS`) or a reported leaflet without PDF
  (`PDF_NOT_FOUND`) is an error (exit 4): a redesign must not look like
  "Completed, 0 leaflets" (it did for weeks in 2026-10).
- `pageUrl` (input, optional) overrides the list URL — used by
  `tests/test_protocol.py` to point at local `file://` fixtures.
- Keep `manifest.json` input/output schemas in sync with `execute`.
- If coop.sk changes markup, refresh the fixtures and keep parser tests green.

## Build / test

```bash
python tests/test_parser.py                         # offline parser tests
python tests/test_protocol.py                        # protocol + execute tests
docker build -t letak-worker-coopjednota .           # production image
docker build -f Dockerfile.test -t lwk-coop-test .   # in-container tests
```
