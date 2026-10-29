"""Protocol-contract tests: run src/main.py as a subprocess and check exit codes,
stdout JSON Lines shape, and --version - all offline via file:// fixtures
(listing -> leaflet page -> InDesign viewer, the shape of coop.sk since 2026-10).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
MAIN_PY = SRC_DIR / "main.py"

ITEMS = [("Potraviny, Supermarket a Tempo", "potraviny-1", "2026-01-01", "2026-01-07"),
         ("Tempo", "tempo-1", "2026-01-01", "2026-01-07"),
         ("Regionálny leták COOP Jednota Nitra", "nitra-1", "2026-01-01", "2026-01-14")]


def _listing_html(items) -> str:
    """The coop.sk/letaky JSON-LD list; items = [(name, slug, from, to)], leaflet pages next to it."""
    els = [{"@type": "ListItem", "position": i + 1,
            "item": {"@type": "DigitalDocument", "url": f"{slug}.html", "name": name,
                     "temporalCoverage": f"{f}T00:00:01+01:00/{t}T23:59:59+01:00"}}
           for i, (name, slug, f, t) in enumerate(items)]
    doc = {"@context": "https://schema.org", "@type": "CollectionPage",
           "mainEntity": {"@type": "ItemList", "numberOfItems": len(els), "itemListElement": els}}
    return f'<html><head><script type="application/ld+json">{json.dumps(doc)}</script></head><body></body></html>'


def _site(tmp: Path, items=ITEMS, viewer=True) -> str:
    """listing -> leaflet pages -> viewer pages, all file:// (the viewer under .../indd.adobe.com/view/)."""
    (tmp / "letaky.html").write_text(_listing_html(items), encoding="utf-8")
    view = tmp / "indd.adobe.com" / "view"
    view.mkdir(parents=True, exist_ok=True)
    for _, slug, _, _ in items:
        (tmp / f"{slug}.html").write_text(
            f'<html><body><iframe src="indd.adobe.com/view/pub-{slug}"></iframe></body></html>', encoding="utf-8")
        manifest = json.dumps({"documentPdf": f"publication-web-resources/pdf/{slug}.pdf"})
        data = json.dumps({"MANIFEST_BODY": manifest, "VERSION_PREFIX": "v1"})
        (view / f"pub-{slug}").write_text(
            f'<script name="reader-view-data">readerViewDataFromServer={data}</script>' if viewer else "<html></html>",
            encoding="utf-8")
    return (tmp / "letaky.html").as_uri()


def _run(stdin_obj, argv=None, env_extra=None):
    env = dict(os.environ)
    env["LOG_LEVEL"] = "Debug"
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, str(MAIN_PY)] + (argv or [])
    return subprocess.run(
        cmd,
        input=(json.dumps(stdin_obj) + "\n") if stdin_obj is not None else "",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _stdout_lines(proc):
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


class VersionFlagTests(unittest.TestCase):
    def test_version_matches_manifest(self):
        manifest = json.loads((SRC_DIR.parent / "manifest.json").read_text(encoding="utf-8"))
        proc = _run(None, argv=["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), manifest["version"])


class SiteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.output_path = self.tmp / "result.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _execute(self, page_url, **overrides):
        payload = {"_action": "execute", "outputPath": str(self.output_path), "pageUrl": page_url,
                   "_meta": {"executionId": "test-exec-id"}}
        payload.update(overrides)
        return _run(payload, env_extra={"LOG_DIR": str(self.tmp / "logs")})


class HappyPathTests(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.url = _site(self.tmp)

    def test_exit_code_zero_and_result_emitted(self):
        proc = self._execute(self.url)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = _stdout_lines(proc)
        for line in lines:
            self.assertIn(line["type"], ("progress", "result", "error"))
        self.assertEqual(lines[-1]["type"], "result")

    def test_only_json_lines_on_stdout(self):
        proc = self._execute(self.url)
        for raw_line in proc.stdout.splitlines():
            if raw_line.strip():
                json.loads(raw_line)

    def test_every_leaflet_is_returned_with_its_pdf(self):
        result = _stdout_lines(self._execute(self.url))[-1]["data"]
        self.assertEqual(result["count"], 3)
        by_type = {lf["type"]: lf for lf in result["leaflets"]}
        self.assertEqual(set(by_type), {"CoopPotraviny", "Tempo", "Regional"})
        tempo = by_type["Tempo"]
        self.assertEqual((tempo["from"], tempo["to"], tempo["id"]), ("2026-01-01", "2026-01-07", "tempo-1"))
        self.assertTrue(tempo["url"].endswith("/view/publication/pub-tempo-1/v1/publication-web-resources/pdf/tempo-1.pdf"))

    def test_type_filter_keeps_the_nationwide_leaflets(self):
        result = _stdout_lines(self._execute(self.url, types=["CoopPotraviny", "Tempo"]))[-1]["data"]
        self.assertEqual(sorted(lf["type"] for lf in result["leaflets"]), ["CoopPotraviny", "Tempo"])

    def test_known_leaflet_is_filtered_out_by_four_part_key(self):
        proc = self._execute(self.url, knownLeaflets=["Tempo|2026-01-01|2026-01-07|tempo-1"])
        result = _stdout_lines(proc)[-1]["data"]
        self.assertEqual(result["count"], 2)
        self.assertNotIn("Tempo", [lf["type"] for lf in result["leaflets"]])

    def test_three_part_key_does_not_filter_anything_out(self):
        result = _stdout_lines(self._execute(self.url, knownLeaflets=["Tempo|2026-01-01|2026-01-07"]))[-1]["data"]
        self.assertEqual(result["count"], 3)

    def test_output_file_is_written(self):
        proc = self._execute(self.url)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(self.output_path.read_text(encoding="utf-8"))["count"], 3)


class SilentFailureTests(SiteTestCase):
    """A changed site layout must surface as an error, never as "Completed, 0 leaflets"."""

    def test_listing_without_leaflets_is_an_error(self):
        (self.tmp / "letaky.html").write_text("<html><body>redesigned page</body></html>", encoding="utf-8")
        proc = self._execute((self.tmp / "letaky.html").as_uri())
        self.assertEqual(proc.returncode, 4)
        self.assertEqual(_stdout_lines(proc)[-1]["code"], "NO_LEAFLETS")

    def test_leaflet_without_pdf_is_an_error(self):
        proc = self._execute(_site(self.tmp, viewer=False), types=["Tempo"])
        self.assertEqual(proc.returncode, 4)
        self.assertEqual(_stdout_lines(proc)[-1]["code"], "PDF_NOT_FOUND")

    def test_unreachable_listing_is_a_dependency_error(self):
        proc = self._execute((self.tmp / "does-not-exist.html").as_uri())
        self.assertEqual(proc.returncode, 4)
        self.assertEqual(_stdout_lines(proc)[-1]["code"], "FETCH_FAILED")


class ErrorPathTests(unittest.TestCase):
    def test_missing_output_path_is_input_error(self):
        proc = _run({"_action": "execute", "_meta": {}})
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(_stdout_lines(proc)[-1]["type"], "error")

    def test_invalid_json_on_stdin_is_input_error(self):
        proc = subprocess.run([sys.executable, str(MAIN_PY)], input="not json\n", capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)

    def test_empty_stdin_is_input_error(self):
        self.assertEqual(_run(None).returncode, 2)

    def test_unknown_action_is_input_error(self):
        self.assertEqual(_run({"_action": "bogus", "_meta": {}}).returncode, 2)


class TerminateActionTests(unittest.TestCase):
    def test_terminate_as_initial_action_returns_cleaned(self):
        proc = _run({"_action": "terminate", "_meta": {}})
        self.assertEqual(proc.returncode, 0)
        lines = _stdout_lines(proc)
        self.assertEqual(lines[-1]["type"], "result")
        self.assertTrue(lines[-1]["data"]["cleaned"])


if __name__ == "__main__":
    unittest.main()
