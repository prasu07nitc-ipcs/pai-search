"""Read-only checks for the Markdown envelope and saved UTF-8 content."""
import os
from pathlib import Path


def check_result(value: dict, actual: dict, expected: dict) -> list[str]:
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    processed = {"url": value.get("url"), "mode": value.get("mode", "balanced"),
                 "include_images": value.get("include_images", True),
                 "include_links": value.get("include_links", True),
                 "include_tables": value.get("include_tables", True)}
    check(set(actual) == {"input", "output", "output_format", "status", "error", "meta_data"}, "Incorrect envelope fields")
    check(actual.get("input") == {"raw_input": value.get("raw_input"), "processed_input": processed},
          "Input must preserve raw request and resolved arguments")
    meta = actual.get("meta_data")
    if not isinstance(meta, dict):
        return failures + ["meta_data must be an object"]
    check(set(meta) == {"requested_url", "final_url", "mode"}, "Incorrect metadata fields")
    check(meta.get("requested_url") == value.get("url"), "requested_url differs from input")
    check(meta.get("mode") == processed["mode"], "mode differs from input/default")
    check(actual.get("output_format") == "markdown", "output_format must be markdown")
    final = meta.get("final_url")
    check(final is None or (isinstance(final, str) and final.startswith(("http://", "https://"))), "Invalid final_url")
    content = ""
    if actual.get("status") == "ok":
        check(actual.get("error") is None, "Success requires null error")
        check(isinstance(final, str) and bool(final), "Success requires final_url")
        if actual.get("output") != f"tool-webpage-markdown/outputs/{os.environ['PROJECT_TOOL_RUN_ID']}.txt":
            return failures + ["Incorrect output path"]
        target = Path(__file__).resolve().parent / "outputs" / (os.environ["PROJECT_TOOL_RUN_ID"] + ".txt")
        try:
            if target.parent.is_symlink() or target.is_symlink() or not target.is_file() or target.stat().st_nlink != 1:
                return failures + ["Output must be a regular unaliased file"]
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return failures + [f"Cannot read Markdown output: {exc}"]
        check(bool(content.strip()), "Output must contain nonempty Markdown")
    elif actual.get("status") == "error":
        check(actual.get("output") is None, "Failure requires null output")
        error = actual.get("error")
        check(isinstance(error, dict) and set(error) == {"code", "message"}
              and all(isinstance(x, str) and bool(x) for x in error.values()), "Invalid error")
    else:
        check(False, "Invalid status")
    for key in expected:
        check(key in {"status", "error_code", "markdown_contains", "variants_nonempty"}, f"Unsupported expectation: {key}")
    if "error_code" in expected:
        check((actual.get("error") or {}).get("code") == expected["error_code"], "Unexpected error code")
    for key in ("markdown_contains", "variants_nonempty"):
        items = expected.get(key, [])
        if not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items):
            check(False, f"{key} must contain nonempty strings")
            continue
        for item in items:
            if key == "markdown_contains":
                check(item in content, f"Missing Markdown substring: {item}")
            else:
                marker = f"# {item}\n\n"
                check(processed["mode"] == "compare" and item in ("balanced", "precision", "recall")
                      and marker in content and bool(content.split(marker, 1)[-1].split("\n\n# ", 1)[0].strip()),
                      f"Missing nonempty variant: {item}")
    return failures
