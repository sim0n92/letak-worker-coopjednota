"""Proc-protocol v1.1 (spec / check / run) and the legacy-execute regression for letak-worker-coopjednota."""
from __future__ import annotations

import json
import sys

import pytest
from jsonschema import Draft202012Validator

from conftest import (FIXTURES, ITEMS, NITRA_KEY, POTRAVINY_KEY, ROOT, TEMPO_KEY, UNREACHABLE, write_site)

sys.path.insert(0, str(ROOT / "src")) if (ROOT / "src").is_dir() else sys.path.insert(0, str(ROOT))
import v11  # noqa: E402

ALL_KEYS = sorted([POTRAVINY_KEY, TEMPO_KEY, NITRA_KEY])


def _keys(result: dict) -> list[str]:
    return [item["key"] for item in result["items"]]


def test_should_return_valid_schemas_when_spec_is_requested(run_action):
    run = run_action("spec")

    assert run.returncode == 0
    assert run.result["protocol"] == "1.1"
    Draft202012Validator.check_schema(run.result["configSchema"])
    Draft202012Validator.check_schema(run.result["outputSchema"])
    assert run.result["configSchema"]["type"] == "object"


def test_should_key_items_by_four_part_leaflet_key_when_run_on_fixture(run_action, fixture_config):
    run = run_action("run", **fixture_config)

    assert run.returncode == 0
    result = run.result
    assert sorted(_keys(result)) == ALL_KEYS
    tempo = next(i for i in result["items"] if i["key"] == TEMPO_KEY)
    assert tempo["url"].endswith("/publication/pub-tempo-1/v1/publication-web-resources/pdf/tempo-1.pdf")
    assert tempo["meta"] == {"type": "Tempo", "validFrom": "2026-01-01", "validTo": "2026-01-07"}
    assert sorted(result["state"]["seen"]) == ALL_KEYS
    assert result["metrics"] == {"leaflets": 3, "newLeaflets": 3}
    assert result["checks"] == [{"name": "leaflets_found", "passed": True, "severity": "error"}]


def test_should_match_output_schema_when_run_on_fixture(run_action, fixture_config):
    spec = run_action("spec").result
    result = run_action("run", **fixture_config).result

    Draft202012Validator(spec["outputSchema"]).validate(result)
    element = spec["outputSchema"]["properties"]["items"]["items"]
    for item in result["items"]:
        Draft202012Validator(element).validate(item)


def test_should_return_no_items_when_run_again_with_returned_state(run_action, fixture_config):
    first = run_action("run", **fixture_config).result

    again = run_action("run", state=first["state"], **fixture_config).result

    assert again["items"] == []
    assert again["state"] == first["state"]
    assert again["metrics"] == {"leaflets": 3, "newLeaflets": 0}


def test_should_not_resolve_pdfs_of_seen_leaflets_when_state_given(run_action, site_dir, fixture_config):
    first = run_action("run", **fixture_config).result
    write_site(site_dir, viewer=False)          # the viewer pages break: a known leaflet must not need them

    again = run_action("run", state=first["state"], **fixture_config)

    assert again.returncode == 0
    assert again.result["items"] == []


def test_should_filter_by_type_but_record_every_key_when_types_given(run_action, fixture_config):
    result = run_action("run", types=["tempo"], **fixture_config).result

    assert _keys(result) == [TEMPO_KEY]
    assert sorted(result["state"]["seen"]) == ALL_KEYS
    assert result["metrics"] == {"leaflets": 3, "newLeaflets": 1}


def test_should_keep_newest_200_when_state_has_250_keys(run_action, fixture_config):
    old = [f"old|{n:03d}|x|y" for n in range(250)]

    result = run_action("run", state={"seen": old}, **fixture_config).result

    seen = result["state"]["seen"]
    assert len(seen) == 200
    assert set(_keys(result)) <= set(seen)
    assert "old|000|x|y" not in seen
    assert "old|249|x|y" in seen


def test_should_treat_known_leaflets_as_seen_when_legacy_param_given(run_action, fixture_config):
    result = run_action("run", knownLeaflets=[TEMPO_KEY], **fixture_config).result

    assert sorted(_keys(result)) == sorted([POTRAVINY_KEY, NITRA_KEY])


def test_should_report_ok_when_check_finds_leaflets(run_action, fixture_config):
    run = run_action("check", **fixture_config)

    assert run.returncode == 0
    assert run.result["ok"] is True


def test_should_report_system_error_when_check_page_has_no_leaflets(run_action, empty_page):
    run = run_action("check", pageUrl=empty_page)

    assert run.returncode == 4
    assert run.error["code"] == "system_error"
    assert "data" not in run.error


def test_should_report_transient_error_with_retry_when_fetch_fails(run_action):
    run = run_action("run", pageUrl=UNREACHABLE)

    assert run.error["code"] == "transient_error"
    assert run.error["data"] == {"retryAfterSec": 300}
    assert run.returncode == 4


def test_should_report_transient_error_when_check_fetch_fails(run_action):
    run = run_action("check", pageUrl=UNREACHABLE)

    assert run.error["code"] == "transient_error"
    assert run.error["data"] == {"retryAfterSec": 300}


def test_should_report_system_error_when_run_finds_no_leaflets(run_action, empty_page):
    run = run_action("run", pageUrl=empty_page)

    assert run.error["code"] == "system_error"
    assert "data" not in run.error


def test_should_report_system_error_when_a_new_leaflet_has_no_pdf(run_action, tmp_path):
    page = write_site(tmp_path / "nopdf", viewer=False)

    run = run_action("run", pageUrl=page)

    assert run.error["code"] == "system_error"


@pytest.mark.parametrize("legacy_code, expected", [
    ("FETCH_FAILED", "transient_error"), ("TIMEOUT", "transient_error"),
    ("NO_LEAFLETS", "system_error"), ("PARSE_FAILED", "system_error"), ("PDF_NOT_FOUND", "system_error"),
    ("INVALID_INPUT", "config_error"), (None, "system_error")])
def test_should_map_legacy_codes_to_protocol_codes_when_classified(legacy_code, expected):
    assert v11.classify(legacy_code) == expected


def test_should_report_config_error_when_state_is_malformed(run_action, fixture_config):
    run = run_action("run", state="not-an-object", **fixture_config)

    assert run.error["code"] == "config_error"
    assert run.returncode == 2


def test_should_report_config_error_when_types_is_not_a_list(run_action, fixture_config):
    run = run_action("run", types="Tempo", **fixture_config)

    assert run.error["code"] == "config_error"


def test_should_emit_only_protocol_lines_when_any_action_runs(run_action, fixture_config, empty_page):
    allowed = {"progress", "result", "error"}
    runs = [
        run_action("spec"),
        run_action("check", **fixture_config),
        run_action("run", **fixture_config),
        run_action("run", state="bad", **fixture_config),
        run_action("check", pageUrl=empty_page),
    ]

    for run in runs:
        assert run.lines
        assert {m["type"] for m in run.lines} <= allowed


def test_should_not_write_any_result_file_when_run_executes(run_action, fixture_config, tmp_path):
    before = set(tmp_path.rglob("*.json"))

    run_action("run", **fixture_config)

    assert set(tmp_path.rglob("*.json")) == before


def test_should_keep_legacy_execute_output_when_unchanged(run_action, fixture_config, tmp_path):
    """Regression: `execute` is byte-compatible with the pre-v1.1 behaviour (snapshot from 1.1.0)."""
    snapshot = json.loads((FIXTURES / "execute_snapshot.json").read_text(encoding="utf-8"))
    out = tmp_path / "out" / "result.json"

    run = run_action("execute", outputPath=str(out), knownLeaflets=[TEMPO_KEY], types=[], **fixture_config)

    assert run.returncode == 0
    result = run.result
    assert set(result) == {"outputPath", "count", "hasNew", "leaflets", "fileSize"}
    got = {k: v for k, v in result.items() if k not in ("outputPath", "fileSize")}
    assert _normalise(got, fixture_config["pageUrl"]) == _normalise(snapshot["result"], None)
    assert result["fileSize"] == out.stat().st_size
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written.pop("source") == fixture_config["pageUrl"]
    assert _normalise(written, fixture_config["pageUrl"]) == _normalise(snapshot["fileDoc"], None)


def _normalise(doc: dict, page_url: str | None) -> dict:
    """The PDF urls are file:// urls of a temp dir: compare their tail (from /indd.adobe.com/)."""
    text = json.dumps(doc, ensure_ascii=False)
    tail = json.loads(text)
    for leaflet in tail["leaflets"]:
        leaflet["url"] = leaflet["url"][leaflet["url"].index("/indd.adobe.com/"):]
    return tail


def test_should_keep_legacy_error_codes_when_execute_fails(run_action, empty_page, tmp_path):
    out = str(tmp_path / "r.json")
    nopdf = write_site(tmp_path / "nopdf", viewer=False)

    empty = run_action("execute", outputPath=out, pageUrl=empty_page)
    unreachable = run_action("execute", outputPath=out, pageUrl=UNREACHABLE)
    no_pdf = run_action("execute", outputPath=out, pageUrl=nopdf)
    missing = run_action("execute")

    assert (empty.returncode, empty.error["code"]) == (4, "NO_LEAFLETS")
    assert (unreachable.returncode, unreachable.error["code"]) == (4, "FETCH_FAILED")
    assert (no_pdf.returncode, no_pdf.error["code"]) == (4, "PDF_NOT_FOUND")
    assert (missing.returncode, missing.error["code"]) == (2, "INVALID_INPUT")


def test_should_declare_all_actions_with_schemas_when_manifest_is_read():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["specVersion"] == "1.1"
    assert set(manifest["actions"]) == {"spec", "check", "run", "execute", "terminate"}
    for name in ("spec", "check", "run"):
        action = manifest["actions"][name]
        assert action["input"]["type"] == "object", name
        assert action["output"]["type"] == "object", name
    assert manifest["actions"]["run"]["input"]["properties"]["state"]
