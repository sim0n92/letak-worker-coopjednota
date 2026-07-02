"""Protocol-contract tests: run src/main.py as a subprocess and check exit codes,
stdout JSON Lines shape, and --version - all offline via file:// fixtures.
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


def _banner_html(record_id: str, title: str, daterange: str) -> str:
    return f"""<html><body>
<div class="_df_thumb" id="df_intro_thumb_{record_id}"
    source="https://coop.sk/files/pdf-file/flip_{record_id}/pdf_{record_id}.pdf"
    thumb="https://coop.sk/files/pdf-file/flip_{record_id}/pdf_{record_id}_thumb.jpg"
    backgroundColor="#f7f9fc">
    {title}
    </div>
    <div class="_df_button" id="df_intro_button">
    <span>{daterange}</span>
    </div>
</body></html>"""


TEMPO_HTML = _banner_html("2001", "Tempo", "01. 01. - 07. 01 .2026")
SUPERMARKET_HTML = _banner_html("2002", "Supermarket", "01. 01. - 07. 01 .2026")
POTRAVINY_HTML = _banner_html("2003", "Potraviny", "01. 01. - 07. 01 .2026")


def _run(stdin_obj, argv=None, env_extra=None):
    env = dict(os.environ)
    env["LOG_LEVEL"] = "Debug"
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, str(MAIN_PY)] + (argv or [])
    proc = subprocess.run(
        cmd,
        input=(json.dumps(stdin_obj) + "\n") if stdin_obj is not None else "",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc


def _stdout_lines(proc):
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


class VersionFlagTests(unittest.TestCase):
    def test_version_matches_manifest(self):
        manifest = json.loads((SRC_DIR.parent / "manifest.json").read_text(encoding="utf-8"))
        proc = _run(None, argv=["--version"])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), manifest["version"])


class HappyPathTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self.tmpdir.name)
        (tmp / "tempo.html").write_text(TEMPO_HTML, encoding="utf-8")
        (tmp / "supermarket.html").write_text(SUPERMARKET_HTML, encoding="utf-8")
        (tmp / "potraviny.html").write_text(POTRAVINY_HTML, encoding="utf-8")
        self.page_urls = {
            "Tempo": (tmp / "tempo.html").as_uri(),
            "Supermarket": (tmp / "supermarket.html").as_uri(),
            "CoopPotraviny": (tmp / "potraviny.html").as_uri(),
        }
        self.output_path = tmp / "result.json"
        self.logs_dir = tmp / "logs"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _execute(self, **overrides):
        payload = {
            "_action": "execute",
            "outputPath": str(self.output_path),
            "pageUrls": self.page_urls,
            "_meta": {"executionId": "test-exec-id"},
        }
        payload.update(overrides)
        return _run(payload, env_extra={"LOG_DIR": str(self.logs_dir)})

    def test_exit_code_zero_and_result_emitted(self):
        proc = self._execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = _stdout_lines(proc)
        self.assertTrue(lines, "expected at least one stdout line")
        for line in lines:
            self.assertIn(line["type"], ("progress", "result", "error"))
        self.assertEqual(lines[-1]["type"], "result")

    def test_only_json_lines_on_stdout(self):
        proc = self._execute()
        for raw_line in proc.stdout.splitlines():
            if raw_line.strip():
                json.loads(raw_line)  # raises if not valid JSON

    def test_all_three_banners_are_returned_as_new(self):
        proc = self._execute()
        result = _stdout_lines(proc)[-1]["data"]
        self.assertEqual(result["count"], 3)
        self.assertTrue(result["hasNew"])
        by_type = {lf["type"]: lf for lf in result["leaflets"]}
        self.assertEqual(by_type["Tempo"]["id"], "2001")
        self.assertEqual(by_type["Tempo"]["from"], "2026-01-01")
        self.assertEqual(by_type["Tempo"]["to"], "2026-01-07")
        self.assertTrue(by_type["Tempo"]["url"].endswith("pdf_2001.pdf"))
        self.assertEqual(by_type["Supermarket"]["id"], "2002")
        self.assertEqual(by_type["CoopPotraviny"]["id"], "2003")

    def test_known_leaflet_is_filtered_out_by_four_part_key(self):
        proc = self._execute(knownLeaflets=["Tempo|2026-01-01|2026-01-07|2001"])
        result = _stdout_lines(proc)[-1]["data"]
        self.assertEqual(result["count"], 2)
        self.assertNotIn("Tempo", {lf["type"] for lf in result["leaflets"]})

    def test_three_part_key_does_not_filter_anything_out(self):
        """Guards the coopjednota-specific 4-part key: a 3-part key (as used by
        other chains) must NOT match, proving the id really is load-bearing."""
        proc = self._execute(knownLeaflets=["Tempo|2026-01-01|2026-01-07"])
        result = _stdout_lines(proc)[-1]["data"]
        self.assertEqual(result["count"], 3)

    def test_type_filter_excludes_non_matching_types(self):
        proc = self._execute(types=["Tempo"])
        result = _stdout_lines(proc)[-1]["data"]
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["leaflets"][0]["type"], "Tempo")

    def test_output_file_is_written(self):
        proc = self._execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.output_path.exists())
        written = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(written["count"], 3)


class ErrorPathTests(unittest.TestCase):
    def test_missing_output_path_is_input_error(self):
        proc = _run({"_action": "execute", "_meta": {}})
        self.assertEqual(proc.returncode, 2)
        lines = _stdout_lines(proc)
        self.assertEqual(lines[-1]["type"], "error")

    def test_invalid_json_on_stdin_is_input_error(self):
        proc = subprocess.run(
            [sys.executable, str(MAIN_PY)],
            input="not json\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 2)

    def test_empty_stdin_is_input_error(self):
        proc = _run(None)
        self.assertEqual(proc.returncode, 2)

    def test_unknown_action_is_input_error(self):
        proc = _run({"_action": "bogus", "_meta": {}})
        self.assertEqual(proc.returncode, 2)

    def test_fetch_failure_on_all_sources_is_dependency_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = (Path(tmp) / "does-not-exist.html").as_uri()
            proc = _run(
                {
                    "_action": "execute",
                    "outputPath": str(Path(tmp) / "result.json"),
                    "pageUrls": {"Tempo": missing, "Supermarket": missing, "CoopPotraviny": missing},
                    "_meta": {},
                }
            )
            self.assertEqual(proc.returncode, 4)
            lines = _stdout_lines(proc)
            self.assertEqual(lines[-1]["type"], "error")
            self.assertEqual(lines[-1].get("code"), "FETCH_FAILED")


class PartialFetchFailureTests(unittest.TestCase):
    def test_one_bad_source_does_not_fail_the_whole_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "tempo.html").write_text(TEMPO_HTML, encoding="utf-8")
            missing = (tmp_path / "does-not-exist.html").as_uri()
            proc = _run(
                {
                    "_action": "execute",
                    "outputPath": str(tmp_path / "result.json"),
                    "pageUrls": {
                        "Tempo": (tmp_path / "tempo.html").as_uri(),
                        "Supermarket": missing,
                        "CoopPotraviny": missing,
                    },
                    "_meta": {},
                },
                env_extra={"LOG_DIR": str(tmp_path / "logs")},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = _stdout_lines(proc)[-1]["data"]
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["leaflets"][0]["type"], "Tempo")


class TerminateActionTests(unittest.TestCase):
    def test_terminate_as_initial_action_returns_cleaned(self):
        proc = _run({"_action": "terminate", "_meta": {}})
        self.assertEqual(proc.returncode, 0)
        lines = _stdout_lines(proc)
        self.assertEqual(lines[-1]["type"], "result")
        self.assertTrue(lines[-1]["data"]["cleaned"])


if __name__ == "__main__":
    unittest.main()
