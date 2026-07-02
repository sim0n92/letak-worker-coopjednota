# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

`letak-worker-coopjednota` is a **ProcMon Process Class** (spec v1.0, type
`stdin`) that parses COOP Jednota Slovensko's three store-banner leaflet
listing pages and reports leaflets not in the caller-supplied `knownLeaflets`
list. Stateless; metadata + URLs only (no downloads).

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
  `id` is the stable internal record id from the PDF path
  (`.../flip_1343/pdf_1343.pdf` → `"1343"`), confirmed stable by its
  `Last-Modified` header being content-bound, not request-time-bound.
- Output leaflets therefore include an explicit `id` field:
  `{type, from, to, id, url}`.
- Anything downstream that builds `knownLeaflets` generically as
  `type|from|to` across all chains needs a coopjednota-specific branch that
  also includes `id`, or coopjednota leaflets will look "new" forever.

This was discussed and agreed with the other worker agents in the shared
`letak-worker` chat room before implementation — see `PLAN.md` for the
decision trail if it needs revisiting.

## Where to work

- Page fetch + parsing lives in `src/coopjednota.py` (pure functions,
  unit-tested against `tests/fixtures/coopjednota_{tempo,supermarket,
  potraviny}.html`). The protocol plumbing is in `src/main.py`
  (`ProcessClass`); `CoopjednotaWorker.execute()` wires the two.
- Three banner pages are fetched per run by default
  (`coopjednota.DEFAULT_URLS`): `/sk/pdfflip/1` (Tempo), `/2` (Supermarket),
  `/3` (Potraviny, reported as type `"CoopPotraviny"` to avoid an ambiguous
  bare "Potraviny"). Each page is a **flat list** of currently active
  leaflets — no current/future tabs like some sibling chains have.
- `type` is assigned from **which page** a leaflet was fetched from (the
  canonical banner name), never from the page's own `_df_thumb` label text —
  that text merely echoes the page context and is not extra signal.
- `pageUrls` (input, optional object) overrides the fetch sources — used by
  `tests/test_protocol.py` to point at local `file://` fixtures instead of
  the real site. Merges over the defaults, so a partial override only
  replaces the given banner(s).
- Keep `manifest.json` input/output schemas in sync with `execute`.
- If coop.sk changes markup, refresh the fixtures and keep parser tests green.

## Build / test

```bash
python tests/test_parser.py                         # offline parser tests
python tests/test_protocol.py                        # protocol + execute tests
docker build -t letak-worker-coopjednota .           # production image
docker build -f Dockerfile.test -t lwk-coop-test .   # in-container tests
```
