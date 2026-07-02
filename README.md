# letak-worker-coopjednota

Process Class (spec v1.0, type `stdin`) that checks COOP Jednota Slovensko's
three store-banner leaflet pages for new leaflets and returns their metadata +
URLs. It does not download anything and keeps no state between runs.

- Leaflet pages: `https://coop.sk/sk/pdfflip/1` (Tempo), `/2` (Supermarket),
  `/3` (Potraviny)
- Protocol spec: `0ics-srls/ProcessMonitor` → `docs/process-class-specification-v1.md`

## How it works

1. Fetch each of the three banner listing pages and parse every leaflet box:
   internal record id, human validity date range, and a directly downloadable
   PDF URL — all present server-side, no headless browser needed.
2. Build a novelty key per leaflet: **`type|from|to|id`** — a 4-part key,
   unlike the 3-part `type|from|to` used by sibling chain workers. This is
   deliberate: COOP Jednota is a federation of regional cooperatives, so the
   same banner can publish multiple distinct leaflets for the same date range
   at once (regional variants), and the page gives no readable region label
   to tell them apart — only the stable internal record `id` does. See
   `CLAUDE.md` for the full rationale.
3. Return only leaflets whose key is not already in the caller-supplied
   `knownLeaflets`, optionally filtered by `types`.

The worker is stateless: the caller (ProcessMonitor) is responsible for
persisting `knownLeaflets` between runs.

## Input (`execute`)

```json
{
  "outputPath": "/abs/path/result.json",
  "knownLeaflets": ["Tempo|2026-07-02|2026-07-08|1343"],
  "types": [],
  "pageUrls": {}
}
```

## Output

```json
{
  "outputPath": "...",
  "count": 4,
  "hasNew": true,
  "leaflets": [
    {"type": "Tempo", "from": "2026-07-02", "to": "2026-07-08", "id": "1343", "url": "https://coop.sk/files/pdf-file/flip_1343/pdf_1343.pdf"},
    {"type": "Tempo", "from": "2026-07-02", "to": "2026-07-08", "id": "1348", "url": "https://coop.sk/files/pdf-file/flip_1348/pdf_1348.pdf"},
    {"type": "Supermarket", "from": "2026-07-02", "to": "2026-07-08", "id": "1343", "url": "https://coop.sk/files/pdf-file/flip_1343/pdf_1343.pdf"},
    {"type": "CoopPotraviny", "from": "2026-07-02", "to": "2026-07-08", "id": "1343", "url": "https://coop.sk/files/pdf-file/flip_1343/pdf_1343.pdf"}
  ],
  "fileSize": 969
}
```

Note the same PDF (`pdf_1343.pdf`) can legitimately appear under multiple
banners at once — the `type|from|to|id` key still gives each a distinct
identity.

## Layout

- `src/coopjednota.py` — pure parsing functions (`fetch`, `parse_leaflets`,
  `leaflet_key`), testable offline.
- `src/main.py` — `ProcessClass` protocol wrapper (stdin/stdout JSON Lines,
  exit codes, `--version`, terminate) + `CoopjednotaWorker.execute()`.
- `manifest.json` — Process Class manifest.
- `tests/fixtures/*.html` — saved snapshots of each banner's listing page.
- `tests/test_parser.py` — offline parser tests against the fixtures.
- `tests/test_protocol.py` — runs `main.py` as a subprocess against local
  `file://` fixtures (via `pageUrls` override) and checks the protocol
  contract (exit codes, JSON Lines shape, `--version`, the 4-part novelty
  key, partial-fetch-failure resilience).

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
