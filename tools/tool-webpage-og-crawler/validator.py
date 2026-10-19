"""Crawler-specific assertions, loaded only by the sandboxed runner during tests."""
from __future__ import annotations

import os


def _check_payload(value: dict, actual: dict, expected: dict) -> list[str]:
    failures = []
    if "error_code" in expected and (actual.get("error") or {}).get("code") != expected["error_code"]:
        failures.append("Unexpected error code")
    if set(actual) != {"requested_url", "final_url", "status", "title", "description", "image", "url", "site_name", "keywords", "datePublished", "dateModified", "error"}:
        failures.append("Incorrect top-level fields")
    for key in ("keywords", "datePublished", "dateModified"):
        if actual.get(key) is not None and not isinstance(actual[key], str):
            failures.append(f"Incorrect {key} type")
    for key, wanted in expected.get("metadata_values", {}).items():
        if actual.get(key) != wanted:
            failures.append(f"Unexpected value for {key}")
    for key in expected.get("required_metadata", []):
        if not actual.get(key):
            failures.append(f"Missing non-empty {key}")
    keys = {"title", "description", "image", "url", "site_name"}
    graph = {key: actual.get(key) for key in keys}
    if not isinstance(graph, dict) or set(graph) != keys or any(item is not None and not isinstance(item, str) for item in graph.values()):
        failures.append("Incorrect Open Graph schema")
        graph = {}
    if actual.get("requested_url") != value["url"]:
        failures.append("requested_url differs from input")
    if expected["status"] == "ok" and not isinstance(actual.get("final_url"), str):
        failures.append("Successful result lacks final_url")
    for key in expected.get("required_properties", []):
        if not graph.get(key):
            failures.append(f"Missing non-empty {key}")
    for key, wanted in expected.get("property_values", {}).items():
        if graph.get(key) != wanted:
            failures.append(f"Unexpected value for {key}")
    return failures


def check_result(value: dict, actual: dict, expected: dict) -> list[str]:
    """Validate the envelope and read only the tool-local JSON result on success."""
    import json
    import re
    from pathlib import Path
    failures = []
    if set(actual) != {"input", "output", "output_format", "status", "error", "meta_data"}:
        failures.append("Incorrect envelope fields")
    processed = {"url": value.get("url")}
    if actual.get("input") != {"raw_input": value.get("raw_input"), "processed_input": processed}:
        failures.append("Input must preserve raw request and resolved arguments")
    meta = actual.get("meta_data")
    if not isinstance(meta, dict) or set(meta) != {"requested_url", "final_url"}:
        return failures + ["Incorrect meta_data fields"]
    if meta.get("requested_url") != value.get("url"):
        failures.append("Metadata requested_url differs from input")
    final = meta.get("final_url")
    if final is not None and (not isinstance(final, str) or not final.startswith(("http://", "https://"))):
        failures.append("Invalid final_url")
    if actual.get("status") == "ok":
        if actual.get("error") is not None or not isinstance(final, str):
            failures.append("Success requires null error and a final URL")
        path = actual.get("output")
        if path != f"tool-webpage-og-crawler/outputs/{os.environ['PROJECT_TOOL_RUN_ID']}.txt":
            return failures + ["Invalid JSON result path"]
        tool_root = Path(__file__).resolve().parent
        target = tool_root / "outputs" / path.rsplit("/", 1)[-1]
        try:
            if (tool_root / "outputs").is_symlink() or target.is_symlink() or target.stat().st_nlink != 1:
                return failures + ["Result path must be a regular unaliased file"]
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return failures + [f"Cannot read JSON result: {exc}"]
        if not isinstance(payload, dict) or set(payload) != {"title", "description", "image", "url", "site_name", "keywords", "datePublished", "dateModified"}:
            return failures + ["Incorrect saved JSON fields"]
    elif actual.get("status") == "error":
        if actual.get("output") is not None:
            failures.append("Error must have null output")
        payload = dict.fromkeys(("title", "description", "image", "url", "site_name", "keywords", "datePublished", "dateModified"))
    else:
        return failures + ["Invalid status"]
    if actual.get("output_format") != "json":
        failures.append("output_format must be json")
    legacy = dict(payload, status=actual.get("status"), error=actual.get("error"),
                  requested_url=meta.get("requested_url"), final_url=meta.get("final_url"))
    failures.extend(_check_payload(value, legacy, expected))
    return failures
