"""Read-only checks for stored bookmarks; loaded only by test workers."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def check_result(value: dict, actual: dict, expected: dict) -> list[str]:
    failures = []
    if actual["input"] != {"raw_input": value["raw_input"], "processed_input": {"page": value["page"]}}:
        failures.append("Input was not preserved.")
    if actual["output_format"] != "markdown":
        failures.append("Expected Markdown output format.")
    if actual["status"] == "error":
        if actual["output"] is not None or actual["meta_data"] != {}:
            failures.append("Errors must have null output and empty metadata.")
        if "error_code" in expected and actual["error"]["code"] != expected["error_code"]:
            failures.append("Unexpected error code.")
        return failures
    page = value["page"]
    domain = urlsplit(page["url"]).hostname.encode("idna").decode("ascii").lower().rstrip(".")
    path = f"data/bookmark/{domain.replace('.', '_')}/{page['page_id']}.md"
    if actual["output"] != path:
        return failures + ["Incorrect domain/page output path."]
    if actual["meta_data"] != {"domain": domain, "page_id": page["page_id"]}:
        failures.append("Incorrect metadata.")
    for key in ("output", "domain"):
        found = actual["output"] if key == "output" else domain
        if key in expected and found != expected[key]:
            failures.append(f"Unexpected {key}.")
    target = Path(os.environ["PROJECT_TRANSACTION_DATA_DIRECTORY"]) / domain.replace(".", "_") / (page["page_id"] + ".md")
    try:
        content = target.read_text(encoding="utf-8")
        for section in ("# ", "## Description", "## Source", "## Identifier", "## Source Code Signature", "- Git repository URL:", "- Git branch:", "- Git commit:", "- Local changes:"):
            if section not in content:
                failures.append(f"Missing section: {section}")
        signature = json.loads(os.environ["PROJECT_TRANSACTION_SOURCE_SIGNATURE"])
        def escaped(value):
            return re.sub(r"([\\`*_{}\[\]<>#+|])", r"\\\1", " ".join(value.split()))
        signature_lines = ["## Source Code Signature", "",
                           "- Git repository URL: " + escaped(signature["repository_url"]),
                           "- Git branch: " + escaped(signature["branch"]),
                           "- Git commit: " + escaped(signature["commit"])]
        if signature["local_changes"]:
            signature_lines += ["- Local changes:"] + ["  - " + escaped(c["status"].replace(" ", ".")) + ": " + escaped(c["path"]) for c in signature["local_changes"]]
        else:
            signature_lines.append("- Local changes: None")
        if not content.endswith("\n".join(signature_lines) + "\n"):
            failures.append("Source signature does not match runner snapshot.")
        if "## Original data" in content:
            failures.append("Original data section must not be rendered.")
        for text in expected.get("contains", []):
            if text not in content:
                failures.append(f"Missing content: {text}")
        for text in expected.get("absent", []):
            if text in content:
                failures.append(f"Unexpected content: {text}")
    except (OSError, ValueError) as exc:
        failures.append(f"Could not validate bookmark: {exc}")
    return failures
