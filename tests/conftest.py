"""Shared fixtures: run the worker as a subprocess against an offline (file://) Coop Jednota site."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAIN = next(p for p in (ROOT / "src" / "main.py", ROOT / "main.py") if p.is_file())  # repo or container layout
FIXTURES = ROOT / "tests" / "fixtures"

ITEMS = [("Potraviny, Supermarket a Tempo", "potraviny-1", "2026-01-01", "2026-01-07"),
         ("Tempo", "tempo-1", "2026-01-01", "2026-01-07"),
         ("Regionálny leták COOP Jednota Nitra", "nitra-1", "2026-01-01", "2026-01-14")]
TEMPO_KEY = "Tempo|2026-01-01|2026-01-07|tempo-1"
POTRAVINY_KEY = "CoopPotraviny|2026-01-01|2026-01-07|potraviny-1"
NITRA_KEY = "Regional|2026-01-01|2026-01-14|nitra-1"
UNREACHABLE = "http://127.0.0.1:9/nope"


@dataclass(frozen=True)
class Run:
    """The outcome of one worker invocation: exit code and the parsed stdout JSON lines."""

    returncode: int
    lines: list[dict[str, Any]]
    stdout: str

    @property
    def result(self) -> dict[str, Any]:
        results = [m for m in self.lines if m.get("type") == "result"]
        assert results, f"no result line in {self.stdout!r}"
        return results[-1]["data"]

    @property
    def error(self) -> dict[str, Any]:
        errors = [m for m in self.lines if m.get("type") == "error"]
        assert errors, f"no error line in {self.stdout!r}"
        return errors[-1]


def listing_html(items=ITEMS) -> str:
    """The coop.sk/letaky JSON-LD list; items = [(name, slug, from, to)]."""
    els = [{"@type": "ListItem", "position": i + 1,
            "item": {"@type": "DigitalDocument", "url": f"{slug}.html", "name": name,
                     "temporalCoverage": f"{f}T00:00:01+01:00/{t}T23:59:59+01:00"}}
           for i, (name, slug, f, t) in enumerate(items)]
    doc = {"@context": "https://schema.org", "@type": "CollectionPage",
           "mainEntity": {"@type": "ItemList", "numberOfItems": len(els), "itemListElement": els}}
    return f'<html><head><script type="application/ld+json">{json.dumps(doc)}</script></head><body></body></html>'


def write_site(directory: Path, items=ITEMS, viewer: bool = True, listing: str | None = None) -> str:
    """listing -> leaflet pages -> viewer pages, all file:// (the viewer under .../indd.adobe.com/view/)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "letaky.html").write_text(listing if listing is not None else listing_html(items), encoding="utf-8")
    view = directory / "indd.adobe.com" / "view"
    view.mkdir(parents=True, exist_ok=True)
    for _, slug, _, _ in items:
        (directory / f"{slug}.html").write_text(
            f'<html><body><iframe src="indd.adobe.com/view/pub-{slug}"></iframe></body></html>', encoding="utf-8")
        manifest = json.dumps({"documentPdf": f"publication-web-resources/pdf/{slug}.pdf"})
        data = json.dumps({"MANIFEST_BODY": manifest, "VERSION_PREFIX": "v1"})
        (view / f"pub-{slug}").write_text(
            f'<script name="reader-view-data">readerViewDataFromServer={data}</script>' if viewer else "<html></html>",
            encoding="utf-8")
    return (directory / "letaky.html").as_uri()


@pytest.fixture
def site_dir(tmp_path: Path) -> Path:
    return tmp_path / "site"


@pytest.fixture
def fixture_config(site_dir: Path) -> dict[str, str]:
    """Offline overrides: the listing page points at a generated local site."""
    return {"pageUrl": write_site(site_dir)}


@pytest.fixture
def empty_page(tmp_path: Path) -> str:
    """A listing page without any leaflet (the site layout changed)."""
    return write_site(tmp_path / "empty-site", listing="<html><body>redesigned page</body></html>")


@pytest.fixture
def run_action(tmp_path: Path):
    """Run the worker with `_action` + params; returns a Run. Logs go to tmp_path."""

    def _run(action: str, **params: Any) -> Run:
        env = {**os.environ, "LOG_DIR": str(tmp_path / "logs"), "PYTHONIOENCODING": "utf-8"}
        payload = json.dumps({"_action": action, **params}, ensure_ascii=False)
        proc = subprocess.run(
            [sys.executable, str(MAIN)], input=payload.encode("utf-8"),
            capture_output=True, env=env, check=False)
        stdout = proc.stdout.decode("utf-8")
        lines = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        return Run(proc.returncode, lines, stdout)

    return _run
