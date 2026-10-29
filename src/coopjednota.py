"""Pure parsing functions for the COOP Jednota Slovensko leaflets.

Since 2026-10 coop.sk lists every active leaflet on ONE page (https://www.coop.sk/letaky) and publishes the
list as JSON-LD (schema.org CollectionPage -> ItemList of DigitalDocument: name, url, temporalCoverage
"start/end"). The old per-banner pages (/sk/pdfflip/1..3) no longer carry leaflets.

A leaflet's own page embeds it in an Adobe InDesign Publish Online iframe (indd.adobe.com/view/<id>). The
viewer page carries the publication manifest: `documentPdf` (the PDF's path inside the publication) and
`VERSION_PREFIX`; the PDF is served at indd.adobe.com/view/publication/<id>/<VERSION_PREFIX>/<documentPdf>.

Banner ("type") from the leaflet name: "Potraviny, Supermarket a Tempo" -> "CoopPotraviny" (the
nationwide leaflet of the small and mid stores), "Tempo" -> "Tempo", "Regionálny leták COOP Jednota <town>"
-> "Regional" (a regional cooperative's own leaflet).

COOP Jednota is a federation of regional cooperatives, so several leaflets can share type and validity
(regional ones); novelty uses a coopjednota-specific 4-part key type|from|to|slug (the slug of the
leaflet's page, e.g. "tempo-43-2026") instead of the 3-part key of the other chains.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

DEFAULT_URL = "https://www.coop.sk/letaky"
DEFAULT_TIMEOUT = 15  # seconds per request

_USER_AGENT = "Mozilla/5.0 (compatible; letak-worker-coopjednota/1.1; +https://github.com/sim0n92/letak-worker-coopjednota)"

_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_IFRAME_RE = re.compile(r'<iframe[^>]*\bsrc="(?P<src>[^"]*indd\.adobe\.com/view/[^"]+)"')
_VIEWER_DATA_RE = re.compile(r"readerViewDataFromServer\s*=\s*(\{.*?\})\s*</script>", re.S)


def fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Fetch a page and return its HTML as text. Not pure - performs I/O."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def banner_of(name: str) -> str:
    """The store banner of a leaflet from its name on the listing."""
    n = " ".join(name.split()).lower()
    if n.startswith("regionálny"):
        return "Regional"
    if "potraviny" in n:
        return "CoopPotraviny"
    if n == "tempo":
        return "Tempo"
    return name.strip()


def parse_listing(html: str, base_url: str = DEFAULT_URL) -> list[dict]:
    """The listing's JSON-LD ItemList -> leaflet stubs (type, name, slug, validity, detail page URL).

    Validity comes from temporalCoverage "2026-10-29T00:00:02+01:00/2026-11-04T23:59:59+01:00": the dates are
    printed in local time (their own offset), so the date part is the Slovak calendar date.
    """
    items = []
    for block in _LD_RE.findall(html):
        try:
            doc = json.loads(block)
        except ValueError:
            continue
        if doc.get("@type") != "CollectionPage":
            continue
        for el in (doc.get("mainEntity") or {}).get("itemListElement") or []:
            item = el.get("item") or {}
            start, _, end = (item.get("temporalCoverage") or "").partition("/")
            if not (item.get("url") and start[:10] and end[:10]):
                continue
            url = urllib.parse.urljoin(base_url, item["url"])
            items.append({
                "type": banner_of(item.get("name") or ""),
                "name": " ".join((item.get("name") or "").split()),
                "slug": re.sub(r"\.html?$", "", url.rstrip("/").rsplit("/", 1)[-1]),
                "validFrom": start[:10],
                "validTo": end[:10],
                "detailUrl": url,
            })
    return items


def parse_viewer_url(detail_html: str, base_url: str) -> str | None:
    """The Adobe InDesign viewer the leaflet page embeds, or None."""
    m = _IFRAME_RE.search(detail_html)
    return urllib.parse.urljoin(base_url, m.group("src")) if m else None


def parse_pdf_url(viewer_html: str, viewer_url: str) -> str | None:
    """The PDF of an InDesign Publish Online publication: <view>/publication/<id>/<VERSION_PREFIX>/<documentPdf>."""
    m = _VIEWER_DATA_RE.search(viewer_html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        manifest = json.loads(data["MANIFEST_BODY"])
        pdf, prefix = manifest["documentPdf"], data["VERSION_PREFIX"]
    except (ValueError, KeyError, TypeError):
        return None
    pub_id = urllib.parse.urlparse(viewer_url).path.rstrip("/").rsplit("/", 1)[-1]
    return urllib.parse.urljoin(viewer_url, f"publication/{pub_id}/{prefix}/{pdf}")


def leaflet_key(leaflet_type: str, valid_from: str, valid_to: str, record_id: str) -> str:
    """coopjednota-specific 4-part novelty key: type|from|to|slug.

    The extra slug is required here because regional leaflets can share type+from+to; other chains use
    the plain 3-part type|from|to key.
    """
    return f"{leaflet_type}|{valid_from}|{valid_to}|{record_id}"
