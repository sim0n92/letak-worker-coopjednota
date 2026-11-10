"""Proc-protocol v1.1 adapter (spec / check / run) for a letak detect class."""
from __future__ import annotations

from typing import Any, Callable

PROTOCOL = "1.1"
ACTIONS = ("spec", "check", "run")
SEEN_LIMIT = 200
RETRY_AFTER_SEC = 300

CONFIG_ERROR = "config_error"
TRANSIENT_ERROR = "transient_error"
SYSTEM_ERROR = "system_error"

CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "types": {"type": "array", "items": {"type": "string"}, "default": []},
        "state": {"type": ["object", "null"], "properties": {"seen": {"type": "array", "items": {"type": "string"}}}},
        "pageUrl": {"type": "string"},          # CHAIN-SPECIFIC: the test override of the listing page
    },
    "additionalProperties": True,
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["items", "state", "metrics", "checks"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object", "required": ["key", "url", "meta"], "properties": {
            "key": {"type": "string", "minLength": 1}, "url": {"type": "string", "minLength": 1},
            "meta": {"type": "object", "required": ["type", "validFrom", "validTo"], "properties": {
                "type": {"type": "string"}, "validFrom": {"type": "string"}, "validTo": {"type": "string"}}}}}},
        "state": {"type": "object", "required": ["seen"], "properties": {"seen": {"type": "array", "items": {"type": "string"}}}},
        "metrics": {"type": "object", "properties": {"leaflets": {"type": "integer"}, "newLeaflets": {"type": "integer"}, "skippedNoPdf": {"type": "integer"}}},
        "checks": {"type": "array"},
    },
}


def spec() -> dict[str, Any]:
    return {"configSchema": CONFIG_SCHEMA, "outputSchema": OUTPUT_SCHEMA, "protocol": PROTOCOL}


def classify(legacy_code: str | None) -> str:
    """Maps a legacy ManagedError code to one of the three protocol error codes."""
    if legacy_code in ("FETCH_FAILED", "TIMEOUT"):
        return TRANSIENT_ERROR
    if legacy_code == "INVALID_INPUT":
        return CONFIG_ERROR
    return SYSTEM_ERROR                          # NO_LEAFLETS, PARSE_FAILED, anything unknown


def error_data(code: str) -> dict[str, Any] | None:
    """`data` of the error line: retryAfterSec only for a transient error."""
    return {"retryAfterSec": RETRY_AFTER_SEC} if code == TRANSIENT_ERROR else None


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def input_problem(input_data: dict[str, Any]) -> str | None:
    """Describes the first invalid config field (types / state / knownLeaflets), None when valid."""
    types = input_data.get("types")
    if types is not None and not _is_str_list(types):
        return "types must be an array of strings"
    state = input_data.get("state")
    if state is not None:
        if not isinstance(state, dict) or (state.get("seen") is not None and not _is_str_list(state["seen"])):
            return "state must be an object {seen: [string]}"
    known = input_data.get("knownLeaflets")
    if known is not None and not _is_str_list(known):
        return "knownLeaflets must be an array of strings"
    return None


def build_run_result(found: list[dict], types: set[str], state_in: dict | None,
                     key_of: Callable[[dict], str], skipped_no_pdf: list[str] | None = None) -> dict[str, Any]:
    """`found` = the leaflets that can be grabbed; `skipped_no_pdf` = names of listed leaflets without a PDF (not Items)."""
    skipped = list(skipped_no_pdf or [])
    checks: list[dict[str, Any]] = [{"name": "leaflets_found", "passed": len(found) + len(skipped) > 0, "severity": "error"}]
    if skipped:
        checks.append({"name": "leaflets_without_pdf", "passed": False, "severity": "warn",
                       "message": f"{len(skipped)} leaflet(s) without a PDF skipped: {', '.join(skipped)}"})
    seen = list((state_in or {}).get("seen") or [])
    known = set(seen)
    keyed = [(it, key_of(it)) for it in found]
    new = [(it, k) for it, k in keyed if k not in known and (not types or (it["type"] or "").lower() in types)]
    seen_out = (seen + [k for _, k in keyed if k not in known])[-SEEN_LIMIT:]
    return {
        "items": [{"key": k, "url": it["url"], "meta": {"type": it["type"], "validFrom": it["from"], "validTo": it["to"]}}
                  for it, k in new],
        "state": {"seen": seen_out},
        "metrics": {"leaflets": len(found) + len(skipped), "newLeaflets": len(new), "skippedNoPdf": len(skipped)},
        "checks": checks,
    }
