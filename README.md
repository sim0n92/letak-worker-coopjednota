# letak-worker-coopjednota

Process Class (spec v1.0, type `stdin`) that checks COOP Jednota Slovensko's
leaflet list for new leaflets and returns their metadata + PDF URLs. It does
not download anything and keeps no state between runs.

- Leaflet list: `https://www.coop.sk/letaky` (since 2026-10; the old per-banner
  pages `/sk/pdfflip/1..3` no longer carry leaflets)
- Protocol spec: `0ics-srls/ProcessMonitor` → `docs/process-class-specification-v1.md`

## How it works

1. Fetch the list and read its JSON-LD (`CollectionPage` → `ItemList` of
   `DigitalDocument`): name, page URL and validity (`temporalCoverage`
   `start/end`, local time — its date part is the validity date).
2. Banner (`type`) from the name: "Potraviny, Supermarket a Tempo" →
   `CoopPotraviny`, "Tempo" → `Tempo`, "Regionálny leták …" → `Regional`.
3. Novelty key **`type|from|to|id`** (`id` = the page slug, e.g.
   `tempo-43-2026`) — a 4-part key, unlike the 3-part key of the sibling
   workers: regional leaflets can share banner and dates (see `CLAUDE.md`).
4. For each new leaflet (after the `types` filter): its page embeds an Adobe
   InDesign Publish Online iframe (`indd.adobe.com/view/<id>`); the viewer's
   `readerViewDataFromServer` carries `documentPdf` and `VERSION_PREFIX`, the
   PDF is `indd.adobe.com/view/publication/<id>/<VERSION_PREFIX>/<documentPdf>`.
5. A list without leaflets is `NO_LEAFLETS`, a reported leaflet without a PDF
   is `PDF_NOT_FOUND` (exit 4) — a site redesign fails loudly instead of
   "Completed, 0 leaflets".

## Input (`execute`)

```json
{
  "outputPath": "/abs/path/result.json",
  "knownLeaflets": ["Tempo|2026-10-29|2026-11-04|tempo-43-2026"],
  "types": ["CoopPotraviny", "Tempo"],
  "pageUrl": "https://www.coop.sk/letaky"
}
```

## Output

```json
{
  "outputPath": "...",
  "count": 2,
  "hasNew": true,
  "leaflets": [
    {"type": "CoopPotraviny", "from": "2026-10-29", "to": "2026-11-04", "id": "potraviny-supermarket-a-tempo-43-2026",
     "url": "https://indd.adobe.com/view/publication/ab1dcc8b-548c-4fd3-bc13-ce94fbf9e679/1/publication-web-resources/pdf/IN4326.pdf"},
    {"type": "Tempo", "from": "2026-10-29", "to": "2026-11-04", "id": "tempo-43-2026",
     "url": "https://indd.adobe.com/view/publication/5d0a98aa-a470-42c7-a99c-bce9850d58f6/0d73/publication-web-resources/pdf/TEMPO_0526_web.pdf"}
  ],
  "fileSize": 722
}
```

## Layout

- `src/coopjednota.py` — pure parsing functions (`fetch`, `parse_listing`,
  `parse_viewer_url`, `parse_pdf_url`, `banner_of`, `leaflet_key`), testable offline.
- `src/main.py` — `ProcessClass` protocol wrapper (stdin/stdout JSON Lines,
  exit codes, `--version`, terminate) + `CoopjednotaWorker.execute()`.
- `manifest.json` — Process Class manifest.
- `tests/fixtures/coop_{letaky,detail,viewer}.html` — snapshots (2026-10) of the list's JSON-LD, a leaflet
  page's iframe and the InDesign viewer's manifest.
- `tests/test_parser.py` — offline parser tests against the fixtures.
- `tests/test_protocol.py` — runs `main.py` as a subprocess against local
  `file://` fixtures (list → leaflet page → viewer, via `pageUrl`) and checks
  the protocol contract (exit codes, JSON Lines shape, `--version`, the 4-part
  novelty key, NO_LEAFLETS / PDF_NOT_FOUND).

## Running tests locally

```bash
python tests/test_parser.py
python tests/test_protocol.py
```

## Running the worker manually

```bash
echo '{"_action":"execute","outputPath":"/tmp/result.json","knownLeaflets":[],"_meta":{"executionId":"local"}}' | python src/main.py
```

## Build

```bash
docker build -t letak-worker-coopjednota .
```

## Test (in container)

```bash
docker build -f Dockerfile.test -t letak-worker-coopjednota-test .
```

## Run (container)

```bash
echo '{"_action":"execute","outputPath":"/out/leaflets.json","knownLeaflets":[]}' \
  | docker run -i -v "$PWD/out:/out" -v "$PWD/logs:/logs" letak-worker-coopjednota
```
