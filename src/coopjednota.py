"""Pure parsing functions for the COOP Jednota Slovensko leaflet pages.

coop.sk renders each leaflet listing server-side (plain HTML, no XHR/JSON), so
pages can be parsed with plain regex - no JS execution needed.

Unlike a single retailer page, COOP Jednota publishes three separate listing
pages, one per store banner ("type"): Tempo, Supermarket, Potraviny (mapped to
"CoopPotraviny" to avoid a bare, ambiguous type name). Each page is a flat list
of currently active leaflets for that banner - no current/future tabs.

COOP Jednota is a federation of regional cooperatives, so the SAME banner can
publish MULTIPLE distinct leaflets for the SAME validity date range at once
(regional variants) - the page gives no readable region/store label to tell
them apart, only a stable internal record id embedded in the PDF path
(".../flip_<id>/pdf_<id>.pdf"). Because of this, novelty here uses a
coopjednota-specific 4-part key (type|from|to|id) instead of the 3-part
type|from|to key used by the other chains - see leaflet_key() below.
"""
from __future__ import annotations

import re
import urllib.request

DEFAULT_URLS = {
    "Tempo": "https://coop.sk/sk/pdfflip/1",
    "Supermarket": "https://coop.sk/sk/pdfflip/2",
    "CoopPotraviny": "https://coop.sk/sk/pdfflip/3",
}
DEFAULT_TIMEOUT = 15  # seconds per request

_USER_AGENT = "Mozilla/5.0 (compatible; letak-worker-coopjednota/1.0; +https://github.com/sim0n92/letak-worker-coopjednota)"

_BOX_RE = re.compile(
    r'<div class="_df_thumb" id="df_intro_thumb_(?P<id>\d+)"\s*'
    r'source="(?P<pdf>[^"]+)"\s*'
    r'thumb="(?P<thumb>[^"]*)"\s*'
    r'backgroundColor="[^"]*">\s*'
    r'(?P<title>[^<]*?)\s*</div>'
    r'.*?<span>(?P<daterange>[^<]*)</span>',
    re.S,
)

_DATE_RANGE_RE = re.compile(
    r"(\d{1,2})\.\s*(\d{1,2})\.\s*-\s*(\d{1,2})\.\s*(\d{1,2})\s*\.\s*(\d{4})"
)


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Fetch a page and return its HTML as text. Not pure - performs I/O."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_date_range(text: str) -> tuple[str, str] | None:
    """Parse "02. 07. - 08. 07 .2026" -> ("2026-07-02", "2026-07-08").

    Only the end year is present in the source text; the start year rolls back
    one year when the start month is after the end month (December -> January).
    """
    m = _DATE_RANGE_RE.search(text)
    if not m:
        return None
    from_day, from_month, to_day, to_month, to_year = (int(g) for g in m.groups())
    from_year = to_year - 1 if from_month > to_month else to_year
    valid_from = f"{from_year:04d}-{from_month:02d}-{from_day:02d}"
    valid_to = f"{to_year:04d}-{to_month:02d}-{to_day:02d}"
    return valid_from, valid_to


def parse_leaflets(html: str, leaflet_type: str) -> list[dict]:
    """Parse a single banner listing page into leaflet records.

    leaflet_type is the canonical banner name for the page this HTML came
    from (one of DEFAULT_URLS' keys) - it is NOT taken from the page's own
    "_df_thumb" label text, which merely echoes the page context and carries
    no extra information.
    """
    leaflets = []
    for m in _BOX_RE.finditer(html):
        date_range = _parse_date_range(m.group("daterange"))
        if not date_range:
            continue
        valid_from, valid_to = date_range
        leaflets.append(
            {
                "type": leaflet_type,
                "id": m.group("id"),
                "validFrom": valid_from,
                "validTo": valid_to,
                "pdfUrl": m.group("pdf"),
                "thumbUrl": m.group("thumb") or None,
            }
        )
    return leaflets


def leaflet_key(leaflet_type: str, valid_from: str, valid_to: str, record_id: str) -> str:
    """coopjednota-specific 4-part novelty key: type|from|to|id.

    The extra `id` (stable internal record id, see module docstring) is
    required here because regional variants can share type+from+to; other
    chains use the plain 3-part type|from|to key.
    """
    return f"{leaflet_type}|{valid_from}|{valid_to}|{record_id}"
