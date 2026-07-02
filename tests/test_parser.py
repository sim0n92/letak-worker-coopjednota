"""Offline tests for src/coopjednota.py against saved HTML fixtures. No network access."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import coopjednota  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class ParseLeafletsTempoTests(unittest.TestCase):
    def setUp(self):
        self.html = _read_fixture("coopjednota_tempo.html")
        self.leaflets = coopjednota.parse_leaflets(self.html, "Tempo")

    def test_finds_all_boxes(self):
        self.assertEqual(len(self.leaflets), 2)

    def test_type_is_the_passed_banner_name(self):
        self.assertTrue(all(lf["type"] == "Tempo" for lf in self.leaflets))

    def test_ids_are_extracted(self):
        ids = {lf["id"] for lf in self.leaflets}
        self.assertEqual(ids, {"1343", "1348"})

    def test_dates_parsed(self):
        for lf in self.leaflets:
            self.assertEqual(lf["validFrom"], "2026-07-02")
            self.assertEqual(lf["validTo"], "2026-07-08")

    def test_pdf_urls_are_absolute(self):
        by_id = {lf["id"]: lf for lf in self.leaflets}
        self.assertEqual(
            by_id["1343"]["pdfUrl"],
            "https://coop.sk/files/pdf-file/flip_1343/pdf_1343.pdf",
        )
        self.assertEqual(
            by_id["1348"]["pdfUrl"],
            "https://coop.sk/files/pdf-file/flip_1348/pdf_1348.pdf",
        )

    def test_no_boxes_found_in_empty_html(self):
        self.assertEqual(coopjednota.parse_leaflets("<html><body>nothing here</body></html>", "Tempo"), [])


class ParseLeafletsSupermarketTests(unittest.TestCase):
    def test_single_leaflet_tagged_with_page_banner_not_embedded_label(self):
        html = _read_fixture("coopjednota_supermarket.html")
        leaflets = coopjednota.parse_leaflets(html, "Supermarket")
        self.assertEqual(len(leaflets), 1)
        self.assertEqual(leaflets[0]["type"], "Supermarket")
        self.assertEqual(leaflets[0]["id"], "1343")


class ParseLeafletsPotravinyTests(unittest.TestCase):
    def test_single_leaflet(self):
        html = _read_fixture("coopjednota_potraviny.html")
        leaflets = coopjednota.parse_leaflets(html, "CoopPotraviny")
        self.assertEqual(len(leaflets), 1)
        self.assertEqual(leaflets[0]["type"], "CoopPotraviny")
        self.assertEqual(leaflets[0]["id"], "1343")


class SameRecordAcrossBannersTests(unittest.TestCase):
    def test_same_pdf_id_can_appear_under_different_banners(self):
        """Regional co-ops can publish the same PDF under multiple banners at
        once - this is exactly why the 4-part key (type|from|to|id) exists:
        the id alone repeats across banners, but type+id together is unique.
        """
        tempo = coopjednota.parse_leaflets(_read_fixture("coopjednota_tempo.html"), "Tempo")
        supermarket = coopjednota.parse_leaflets(_read_fixture("coopjednota_supermarket.html"), "Supermarket")
        tempo_ids = {lf["id"] for lf in tempo}
        supermarket_ids = {lf["id"] for lf in supermarket}
        self.assertTrue(tempo_ids & supermarket_ids)


class ParseDateRangeTests(unittest.TestCase):
    def test_year_rollover_handled(self):
        html = (
            '<div class="_df_thumb" id="df_intro_thumb_9001" '
            'source="https://coop.sk/files/pdf-file/flip_9001/pdf_9001.pdf" '
            'thumb="https://coop.sk/files/pdf-file/flip_9001/pdf_9001_thumb.jpg" '
            'backgroundColor="#fff">Tempo</div>'
            '<div class="_df_button"><span>29. 12. - 04. 01 .2027</span></div>'
        )
        leaflets = coopjednota.parse_leaflets(html, "Tempo")
        self.assertEqual(len(leaflets), 1)
        self.assertEqual(leaflets[0]["validFrom"], "2026-12-29")
        self.assertEqual(leaflets[0]["validTo"], "2027-01-04")


class LeafletKeyTests(unittest.TestCase):
    def test_key_format(self):
        self.assertEqual(
            coopjednota.leaflet_key("Tempo", "2026-07-02", "2026-07-08", "1343"),
            "Tempo|2026-07-02|2026-07-08|1343",
        )

    def test_same_type_and_dates_different_id_produce_different_keys(self):
        k1 = coopjednota.leaflet_key("Tempo", "2026-07-02", "2026-07-08", "1343")
        k2 = coopjednota.leaflet_key("Tempo", "2026-07-02", "2026-07-08", "1348")
        self.assertNotEqual(k1, k2)

    def test_different_types_same_dates_and_id_produce_different_keys(self):
        k1 = coopjednota.leaflet_key("Tempo", "2026-07-02", "2026-07-08", "1343")
        k2 = coopjednota.leaflet_key("Supermarket", "2026-07-02", "2026-07-08", "1343")
        self.assertNotEqual(k1, k2)


if __name__ == "__main__":
    unittest.main()
