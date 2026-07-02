# letak-worker-coopjednota — Implementation Plan

## Overview
ProcMon Process Class (spec v1.0, type: `stdin`) that detects new leaflets
across COOP Jednota Slovensko's three store banners (Tempo, Supermarket,
Potraviny) and reports them.

## Design decisions (locked)
- **Novelty**: stateless — caller passes `knownLeaflets` (keys); worker
  returns the ones not listed + `hasNew`.
- **Novelty key — 4 parts, `type|from|to|id`** (deviation from the 3-part
  `type|from|to` used by kaufland/billa/tesco/lidl). Reasoning, verified live
  on 2026-07-02:
  - COOP Jednota is a federation of regional cooperatives. Confirmed on
    `/sk/pdfflip/1` (Tempo): two leaflets (`flip_1343`, `flip_1348`) both
    dated `02.07.-08.07.2026` at the same time — a plain `type|from|to` key
    would collide and silently drop one.
  - Checked for a readable region/store discriminator near each leaflet box
    (kraj/okres/predajňa/družstvo/region/chain/store, in Slovak and English)
    — none found; only the type label (redundant with page context), dates,
    and PDF/thumb URLs are present.
  - Verified `id` (the numeric record id in the PDF path,
    `flip_1343/pdf_1343.pdf` → `"1343"`) is stable: re-fetched the same page
    twice, ids were identical both times (only CSRF token and image
    cache-busting query params differed); the PDF itself has a
    `Last-Modified` header bound to content, not request time.
  - Agreed with `kaufland-worker-agent` (coordinator) in the shared
    `letak-worker` chat room before implementing: output leaflets carry an
    explicit `id` field (`{type, from, to, id, url}`) so the key is
    reconstructible by the orchestrator — not just embedded invisibly.
    Simon (human) was notified of this contract deviation.
- **Type naming**: page `/1` → `"Tempo"`, `/2` → `"Supermarket"`,
  `/3` → `"CoopPotraviny"` (not bare `"Potraviny"`, to avoid ambiguity) —
  assigned by which page a leaflet was fetched from, not from the page's own
  `_df_thumb` label text (which just echoes page context).
- **Output**: PDF entries `{type, from, to, id, url}` — no viewer URLs.
- **Scope**: URLs only; no PDF/asset downloading (left to a downstream step).
- **Fetch overrides**: `pageUrls` (object, banner name → URL) merges over the
  three production defaults — not a single `pageUrl` string like sibling
  workers, since coopjednota genuinely has three independent listing pages.
  Enables offline `file://`-based protocol tests without touching sibling
  workers' single-URL convention.
- **Partial fetch failure**: if one banner page fails to fetch, log a warning
  and continue with the others; only raise `FETCH_FAILED` (exit 4) if *all*
  fail. A single flaky banner shouldn't sink the whole run.

## Status — DONE
```
manifest.json     # spec v1.0, knownLeaflets in / hasNew+leaflets(+id) out ... DONE
Dockerfile        # python:3.12-alpine, stdin entrypoint .................... DONE
Dockerfile.test   # protocol + parser tests ................................ DONE
src/main.py       # ProcMon stdin/stdout protocol wrapper + Worker .......... DONE
src/coopjednota.py # fetch + parse_leaflets + leaflet_key (4-part) ......... DONE
tests/            # test_protocol.py, test_parser.py, 3 fixtures ........... DONE
```
Verified live against the real site (all 3 banners, 4 leaflets incl. the
Tempo regional-variant pair) and offline against fixtures; both `docker
build .` and `docker build -f Dockerfile.test .` pass.

## How it works (implemented)
- Plain HTTP fetch (`urllib`) — all 3 pages are static server-rendered HTML,
  no headless browser needed.
- `parse_leaflets(html, leaflet_type)`: regex over `_df_thumb`/`_df_button`
  box markup, one box per leaflet; `leaflet_type` is passed in by the caller
  (the banner the page belongs to), not read from the box's own label.
- `main.py` fetches `coopjednota.DEFAULT_URLS` (overridable via `pageUrls`),
  aggregates all three banners' leaflets, then filters by `types` and the
  4-part novelty key before writing output.

## Open / future ideas
1. **Regional dedup** — if coop.sk ever exposes a real region/store label per
   leaflet, prefer folding it into `type` (e.g. `"Tempo-Košice"`) over the
   `id`-based key, per the coordinator's original suggestion — would let the
   key stay visually meaningful. Re-check next time markup changes.
2. **id stability over time** — confirmed stable across repeated fetches of
   the same page load; not yet confirmed across a real re-upload/correction
   of an existing leaflet (would need to observe across a content update).
   If it turns out ids get reused/rotated, revisit the key scheme.
3. **Fixture refresh** — `tests/fixtures/coopjednota_*.html` are snapshots
   from 2026-07-02; refresh if coop.sk changes markup, keep parser tests
   green.

## Build / test
```bash
python tests/test_parser.py && python tests/test_protocol.py   # local
docker build -t letak-worker-coopjednota .
docker build -f Dockerfile.test -t letak-worker-coopjednota-test .
```
