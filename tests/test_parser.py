"""Offline tests for src/coopjednota.py against saved HTML fixtures (coop.sk as of 2026-10). No network access."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import coopjednota  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VIEWER_URL = "https://indd.adobe.com/view/5d0a98aa-a470-42c7-a99c-bce9850d58f6"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class ParseListingTests(unittest.TestCase):
    def setUp(self):
        self.stubs = coopjednota.parse_listing(_read_fixture("coop_letaky.html"))

    def test_finds_every_leaflet_of_the_list(self):
        self.assertEqual(len(self.stubs), 12)

    def test_nationwide_leaflets_get_their_banner(self):
        by_type = {s["type"]: s for s in self.stubs if s["type"] != "Regional"}
        self.assertEqual(set(by_type), {"CoopPotraviny", "Tempo"})
        self.assertEqual(by_type["Tempo"]["slug"], "tempo-43-2026")
        self.assertEqual(by_type["CoopPotraviny"]["detailUrl"],
                         "https://www.coop.sk/letaky/potraviny-supermarket-a-tempo-43-2026")

    def test_regional_leaflets_are_typed_regional(self):
        self.assertEqual(sum(s["type"] == "Regional" for s in self.stubs), 10)

    def test_validity_is_the_local_calendar_date(self):
        tempo = next(s for s in self.stubs if s["type"] == "Tempo")
        self.assertEqual((tempo["validFrom"], tempo["validTo"]), ("2026-10-29", "2026-11-04"))

    def test_no_leaflets_in_a_page_without_json_ld(self):
        self.assertEqual(coopjednota.parse_listing("<html><body>redesigned</body></html>"), [])


class BannerTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(coopjednota.banner_of("Potraviny, Supermarket a Tempo"), "CoopPotraviny")
        self.assertEqual(coopjednota.banner_of("Tempo"), "Tempo")
        self.assertEqual(coopjednota.banner_of("Regionálny leták  COOP Jednota Revúca"), "Regional")


class ViewerAndPdfTests(unittest.TestCase):
    def test_viewer_url_from_the_leaflet_page(self):
        url = coopjednota.parse_viewer_url(_read_fixture("coop_detail.html"),
                                           "https://www.coop.sk/letaky/tempo-43-2026")
        self.assertEqual(url, VIEWER_URL)

    def test_no_viewer_in_a_page_without_iframe(self):
        self.assertIsNone(coopjednota.parse_viewer_url("<html></html>", "https://www.coop.sk/letaky/x"))

    def test_pdf_url_from_the_viewer_manifest(self):
        self.assertEqual(coopjednota.parse_pdf_url(_read_fixture("coop_viewer.html"), VIEWER_URL),
                         "https://indd.adobe.com/view/publication/5d0a98aa-a470-42c7-a99c-bce9850d58f6/0d73/"
                         "publication-web-resources/pdf/TEMPO_0526_web.pdf")

    def test_no_pdf_without_viewer_data(self):
        self.assertIsNone(coopjednota.parse_pdf_url("<html></html>", VIEWER_URL))


class LeafletKeyTests(unittest.TestCase):
    def test_four_part_key(self):
        self.assertEqual(coopjednota.leaflet_key("Tempo", "2026-10-29", "2026-11-04", "tempo-43-2026"),
                         "Tempo|2026-10-29|2026-11-04|tempo-43-2026")


if __name__ == "__main__":
    unittest.main()
