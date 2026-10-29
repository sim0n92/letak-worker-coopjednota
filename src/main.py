#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import coopjednota

EXIT_OK, EXIT_ERROR, EXIT_INPUT, EXIT_TIMEOUT, EXIT_DEPENDENCY = 0, 1, 2, 3, 4
LOG_DIR = Path(os.environ.get("LOG_DIR", "/logs"))
LOG_FILE = LOG_DIR / "events.log"
_LEVEL_MAP = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
_LEVEL_ABBREV = {logging.DEBUG: "DBG", logging.INFO: "INF", logging.WARNING: "WRN", logging.ERROR: "ERR", logging.CRITICAL: "ERR"}


class _SerilogFormatter(logging.Formatter):
    def format(self, r):
        ts = datetime.fromtimestamp(r.created).strftime("%Y-%m-%d %H:%M:%S.") + f"{int(r.msecs):03d}"
        return f"{ts} [{_LEVEL_ABBREV.get(r.levelno, 'INF')}] {r.getMessage()}"


class ManagedError(Exception):
    def __init__(self, message, *, code=None, exit_code=EXIT_ERROR, data=None):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.data = data


def _find_manifest():
    here = Path(__file__).resolve().parent
    for c in (here / "manifest.json", here.parent / "manifest.json"):
        if c.is_file():
            return c
    return None


def _manifest_version():
    mf = _find_manifest()
    if mf:
        try:
            return json.loads(mf.read_text(encoding="utf-8")).get("version", "0.0.0")
        except Exception:
            pass
    return "0.0.0"


class ProcessClass:
    def __init__(self):
        self.logger = self._setup_logging()
        self._input_data: dict[str, Any] = {}
        self._meta: dict[str, Any] = {}
        self.terminate_requested = threading.Event()

    @staticmethod
    def _emit(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def report(self, percent, message):
        self._emit({"type": "progress", "percent": percent, "message": message})

    def _emit_result(self, data):
        self._emit({"type": "result", "data": data})

    def _emit_error(self, message, code, data):
        m = {"type": "error", "message": message}
        if code:
            m["code"] = code
        if data:
            m["data"] = data
        self._emit(m)

    def _setup_logging(self):
        level = _LEVEL_MAP.get(os.environ.get("LOG_LEVEL", "Info").lower(), logging.INFO)
        lg = logging.getLogger("letak-worker-coopjednota")
        lg.setLevel(level)
        lg.handlers.clear()
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            h = logging.FileHandler(LOG_FILE, encoding="utf-8")
        except Exception:
            h = logging.StreamHandler(sys.stderr)
        h.setFormatter(_SerilogFormatter())
        lg.addHandler(h)
        lg.propagate = False
        return lg

    def _watch_stdin_for_terminate(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("_action") == "terminate":
                self.logger.info("Terminate received via stdin during execution")
                self.terminate_requested.set()
                return

    def _start_terminate_watcher(self):
        threading.Thread(target=self._watch_stdin_for_terminate, daemon=True).start()

    def run(self, argv=None):
        argv = sys.argv[1:] if argv is None else argv
        if argv and argv[0] == "--version":
            print(_manifest_version())
            return EXIT_OK
        first_line = sys.stdin.readline()
        if not first_line.strip():
            self.logger.error("Empty stdin")
            self._emit_error("Empty stdin: expected a JSON message", "EMPTY_INPUT", None)
            return EXIT_INPUT
        try:
            message = json.loads(first_line)
        except json.JSONDecodeError as e:
            self._emit_error(f"Invalid JSON on stdin: {e}", "INVALID_JSON", None)
            return EXIT_INPUT
        action = message.get("_action")
        self._meta = message.get("_meta", {}) or {}
        self._input_data = {k: v for k, v in message.items() if not k.startswith("_")}
        try:
            if action == "execute":
                self._start_terminate_watcher()
                return self._handle_execute()
            if action == "terminate":
                return self._handle_terminate()
            raise ManagedError(f"Unknown action: {action!r}", code="UNKNOWN_ACTION", exit_code=EXIT_INPUT)
        except ManagedError as e:
            self.logger.error("%s", e)
            self._emit_error(str(e), e.code, e.data)
            return e.exit_code
        except Exception as e:
            self.logger.error("Unhandled error: %s", e)
            import traceback

            traceback.print_exc(file=sys.stderr)
            return EXIT_ERROR

    def _handle_execute(self):
        self.report(0, "Starting...")
        data = self.execute(self._input_data)
        self.report(100, "Done")
        self._emit_result(data)
        return EXIT_OK

    def _handle_terminate(self):
        self.report(0, "Termination requested...")
        self._emit_result({"cleaned": self.terminate()})
        return EXIT_OK

    def execute(self, input_data):
        raise NotImplementedError

    def terminate(self):
        self.terminate_requested.set()
        return True


class CoopjednotaWorker(ProcessClass):
    def execute(self, input_data):
        output_path = input_data.get("outputPath")
        if not output_path:
            raise ManagedError("Missing required input field: outputPath", code="INVALID_INPUT", exit_code=EXIT_INPUT)
        known = set(input_data.get("knownLeaflets") or [])
        wanted = {str(t).lower() for t in (input_data.get("types") or [])}
        url = input_data.get("pageUrl") or coopjednota.DEFAULT_URL

        self.report(10, f"Fetching {url}")
        try:
            listing = coopjednota.fetch(url)
        except Exception as e:
            raise ManagedError(f"Failed to fetch leaflet list: {e}", code="FETCH_FAILED", exit_code=EXIT_DEPENDENCY) from e
        stubs = coopjednota.parse_listing(listing, base_url=url)
        if not stubs:
            # the list always carries the current leaflets: none parsed = the page layout changed
            raise ManagedError(f"No leaflets found on {url} - page layout changed?", code="NO_LEAFLETS",
                               exit_code=EXIT_DEPENDENCY)
        stubs = [s for s in stubs if (not wanted or s["type"].lower() in wanted)
                 and coopjednota.leaflet_key(s["type"], s["validFrom"], s["validTo"], s["slug"]) not in known]

        # leaflet page -> InDesign viewer -> PDF, only for the leaflets we report
        matched, no_pdf = [], []
        for i, s in enumerate(stubs):
            if self.terminate_requested.is_set():
                raise ManagedError("Terminated during fetch", code="TERMINATED", exit_code=EXIT_ERROR)
            self.report(20 + int(60 * i / max(len(stubs), 1)), f"Resolving PDF of {s['name']}")
            pdf = None
            try:
                viewer = coopjednota.parse_viewer_url(coopjednota.fetch(s["detailUrl"]), s["detailUrl"])
                if viewer:
                    pdf = coopjednota.parse_pdf_url(coopjednota.fetch(viewer), viewer)
            except Exception as e:
                self.logger.warning("Failed to resolve the PDF of %s: %s", s["detailUrl"], e)
            if not pdf:
                no_pdf.append(s["name"]); continue
            matched.append({"type": s["type"], "from": s["validFrom"], "to": s["validTo"], "id": s["slug"], "url": pdf})
        if no_pdf:
            raise ManagedError(f"No PDF found for {no_pdf} - leaflet page or viewer layout changed?",
                               code="PDF_NOT_FOUND", exit_code=EXIT_DEPENDENCY)

        self.report(90, "Writing output")
        result_doc = {
            "source": url,
            "types": sorted(wanted) or None,
            "hasNew": bool(matched),
            "count": len(matched),
            "leaflets": matched,
        }
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result_doc, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "outputPath": str(out),
            "count": len(matched),
            "hasNew": bool(matched),
            "leaflets": matched,
            "fileSize": out.stat().st_size,
        }


if __name__ == "__main__":
    sys.exit(CoopjednotaWorker().run())
