"""Offline requirement-to-bookmark keyword retrieval through the project runner."""
from __future__ import annotations

import json
import math
from collections import Counter
from urllib.parse import urlsplit
import os
from pathlib import Path
import re
import uuid


class _Failure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("’", "'").split())


def _regular(path: Path, code: str) -> None:
    if path.resolve() != path or not path.is_file() or path.stat().st_nlink != 1:
        raise _Failure(code, "Sources must be regular files without filesystem aliases.")


def _table(text: str, heading: str, columns: tuple) -> list:
    sections = re.split(r"(?m)^# " + re.escape(heading) + r"\s*$", text)
    if len(sections) != 2:
        raise _Failure("invalid_requirement", "Missing or duplicate section: " + heading)
    body = re.split(r"(?m)^# ", sections[1])[0]
    rows = [tuple(c.strip() for c in line.strip().split("|")[1:-1])
            for line in body.splitlines() if line.strip().startswith("|")]
    if (len(rows) < 3 or rows[0] != columns or len(rows[1]) != len(columns)
            or any(not re.fullmatch(r":?-{3,}:?", c) for c in rows[1])
            or any(len(row) != len(columns) or not all(row) for row in rows[2:])):
        raise _Failure("invalid_requirement", "Invalid or empty table: " + heading)
    return rows[2:]


def _intent(text: str) -> str:
    """Preserve User Query followed by Intent and its subsections verbatim."""
    sections = list(re.finditer(r"(?m)^# Intent[ \t]*$", text))
    if len(sections) != 1:
        raise _Failure("invalid_requirement", "Missing or duplicate section: Intent")
    queries = list(re.finditer(r"(?m)^# User Query[ \t]*$", text))
    if len(queries) != 1:
        raise _Failure("invalid_requirement", "Missing or duplicate section: User Query")
    start = queries[0].start()
    next_heading = re.search(r"(?m)^# ", text[queries[0].end():])
    if (next_heading is None
            or queries[0].end() + next_heading.start() != sections[0].start()):
        raise _Failure("invalid_requirement", "User Query must immediately precede Intent.")
    following = re.search(r"(?m)^# ", text[sections[0].end():])
    end = sections[0].end() + following.start() if following else len(text)
    intent = text[sections[0].start():end]
    for heading in ("Interpreted context", "Uncertainty"):
        if len(re.findall(r"(?m)^## " + re.escape(heading) + r"[ \t]*$", intent)) != 1:
            raise _Failure("invalid_requirement", "Missing or duplicate subsection: " + heading)
    return text[start:end]


def _bookmark_fields(text: str) -> tuple:
    """Read the explicit Source URL and structured bookmark entity list."""
    urls = re.findall(r"(?m)^- URL:\s*(\S+)\s*$", text)
    url = urls[0] if len(urls) == 1 else ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _Failure("corpus_error", "Each matched bookmark requires one valid HTTP(S) Source URL.")
    sections = re.split(r"(?m)^## Entities[ \t]*$", text)
    if len(sections) > 2:
        raise _Failure("corpus_error", "Duplicate bookmark Entities sections.")
    entities = []
    if len(sections) == 2:
        body = re.split(r"(?m)^#{1,2} ", sections[1])[0]
        entities = [match.group(1).strip() for match in re.finditer(r"(?m)^- (.+)$", body)]
    return url, entities


def _cell(value: str) -> str:
    import html
    return html.escape(value, quote=True).replace("|", "&#124;").replace("\n", " ")


def _utterances(text: str) -> list:
    """Read every indexed utterance, including four-space continuation lines."""
    values = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('- Utterance: '):
            parts = [line[len('- Utterance: '):]]
            for continuation in lines[index + 1:]:
                if not continuation.startswith('    '):
                    break
                parts.append(continuation[4:])
            value = '\n'.join(parts)
            if not value.strip():
                raise _Failure('corpus_error', 'Indexed utterance is empty.')
            values.append(value)
    if not values:
        raise _Failure('corpus_error', 'Indexed utterances.md contains no utterances.')
    return values


def _collect_utterances(root: Path, entities: list, mode: str, threshold: float) -> tuple:
    """Resolve names once, then read all indexed pages for accepted folders."""
    metadata = {'entity_matches': [], 'unmatched_entities': [],
                'ambiguous_entities': [], 'utterance_files': 0, 'utterance_count': 0}
    rows = []
    if not entities:
        return rows, metadata
    index = root / 'data/index'
    if index.resolve() != index or not index.is_dir():
        raise _Failure('corpus_error', 'Index root must be a real directory.')
    names = {}
    for folder in sorted(index.iterdir()):
        if folder.is_symlink():
            raise _Failure('corpus_error', 'Index entity symlinks are forbidden.')
        if folder.is_dir():
            names.setdefault(_normalize(folder.name), []).append(folder)
    choices = sorted(names)
    if mode == 'fuzzy':
        try:
            from rapidfuzz import fuzz, process
        except ImportError as exc:
            raise _Failure('missing_dependency', 'Fuzzy matching requires the declared RapidFuzz dependency.') from exc
    cache = {}
    for entity in entities:
        key = _normalize(entity)
        candidates = names.get(key, [])
        score = 100.0
        method = 'exact'
        if not candidates and mode == 'fuzzy':
            hits = process.extract(key, choices, scorer=fuzz.ratio, processor=None,
                                   score_cutoff=max(0, threshold - 3), limit=2)
            if hits and hits[0][1] >= threshold:
                if len(hits) > 1 and hits[0][1] - hits[1][1] < 3:
                    metadata['ambiguous_entities'].append(entity)
                    continue
                candidates = names[hits[0][0]]
                score = hits[0][1]
                method = 'fuzzy'
        if not candidates:
            metadata['unmatched_entities'].append(entity)
            continue
        if len(candidates) != 1:
            metadata['ambiguous_entities'].append(entity)
            continue
        folder = candidates[0]
        metadata['entity_matches'].append({'entity_name': entity, 'index_entity': folder.name,
                                           'method': method, 'score': score})
        if folder not in cache:
            collected = set()
            for base, dirs, files in os.walk(folder, followlinks=False,
                                              onerror=lambda e: (_ for _ in ()).throw(e)):
                for name in dirs:
                    if (Path(base) / name).is_symlink():
                        raise _Failure('corpus_error', 'Index directory symlinks are forbidden.')
                if 'utterances.md' not in files:
                    continue
                source = Path(base) / 'utterances.md'
                _regular(source, 'corpus_error')
                relative = source.relative_to(folder)
                page_id = source.parent.name
                if len(relative.parts) != 3 or not re.fullmatch(r'[0-9a-f]{64}', page_id):
                    raise _Failure('corpus_error', 'Invalid indexed utterance path or page ID.')
                for utterance in _utterances(source.read_text(encoding='utf-8')):
                    collected.add((relative.parts[0], page_id, utterance))
                metadata['utterance_files'] += 1
            cache[folder] = sorted(collected, key=lambda item: (item[1], item[2], item[0]))
        rows.extend((entity, domain, page_id, utterance)
                    for domain, page_id, utterance in cache[folder])
    metadata['utterance_count'] = len(rows)
    return rows, metadata


def _render(pages: list, page_entities: dict, root: Path,
            entity_match: str, fuzzy_threshold: float) -> tuple:
    lines = ["# Matching pages", "", "| page_id | url | keywords | entities |",
             "|---|---|---|---|"]
    for page in pages:
        url = _cell(page["url"])
        lines.append("| " + " | ".join((_cell(page["page_id"]), url,
                     "<br>".join(_cell(k) for k in page["keywords"]) or "—",
                     "<br>".join(_cell(e) for e in page["entities"]) or "—")) + " |")
    if not pages:
        lines.extend(["", "No matching pages."])
    counts, labels, matching, listed = Counter(), {}, set(), set()
    for page in pages:
        distinct = set()
        matching.update(_normalize(entity) for entity in page["entities"])
        listed.update(_normalize(entity) for entity in page_entities[page["page_id"]])
        for entity in page_entities[page["page_id"]] + page["entities"]:
            key = _normalize(entity)
            labels.setdefault(key, entity)
            distinct.add(key)
        counts.update(distinct)
    scores = {}
    for key in counts:
        frequency = counts[key] / len(pages)
        if key in matching and key in listed:
            scores[key] = 0.75 + 0.25 * frequency
        elif key in matching:
            scores[key] = 0.50 + 0.24 * frequency
        else:
            scores[key] = 0.49 * frequency
    lines.extend(["", "# Entities", "",
                  "Rank order: entities in both sources, matching-column-only entities, "
                  "then bookmark-only entities by distinct matched-page count. "
                  "Bookmark-only entities found in one page rank lowest. "
                  "Let f = distinct matched pages containing the entity / total matched pages. "
                  "Relevance: both sources = 0.75 + 0.25f; matching column only = 0.50 + 0.24f; "
                  "bookmark Entities sections only = 0.49f. "
                  "Source membership is evaluated across all matched pages; each entity counts once per page.", "",
                  "| entity_name | relevance |", "|---|---|"])
    ranked = sorted(counts, key=lambda key: (-scores[key], -counts[key], key))
    utterances, metadata = _collect_utterances(
        root, [labels[key] for key in ranked], entity_match, fuzzy_threshold)
    with_utterances = {_normalize(entity) for entity, _, _, _ in utterances}
    ranked = [key for key in ranked if key in with_utterances]
    for key in ranked:
        lines.append(f"| {_cell(labels[key])} | {scores[key]:.4f} |")
    if not ranked:
        lines.extend(["", "No entities with indexed utterances found."])
    lines.extend(['', '# Utterances', '', '| entity_name | domain | page_id | utterance |', '|---|---|---|---|'])
    for entity, domain, page_id, utterance in utterances:
        lines.append('| ' + ' | '.join((_cell(entity), _cell(domain), _cell(page_id),
                     '<br>'.join(_cell(line) for line in utterance.split('\n')))) + ' |')
    if not utterances:
        lines.extend(['', 'No indexed utterances found for the ranked entities.'])
    return "\n".join(lines) + "\n", metadata


def search_bookmarks(raw_input: str, entity_match: str = 'exact',
                     fuzzy_threshold: float = 95.0) -> dict:
    """Search a requirement and index; exact by default, optional fuzzy threshold 0–100."""
    result = {"input": {"raw_input": raw_input, "processed_input": {
                  'entity_match': entity_match, 'fuzzy_threshold': fuzzy_threshold}},
              "output": None, "output_format": "markdown", "status": "error",
              "error": None, "meta_data": {}}
    phase = "invalid_input"
    try:
        if entity_match not in ('exact', 'fuzzy') or not math.isfinite(fuzzy_threshold) or not 0 <= fuzzy_threshold <= 100:
            raise _Failure('invalid_input', 'entity_match must be exact or fuzzy; fuzzy_threshold must be finite and between 0 and 100.')
        root = Path(__file__).resolve().parents[2]
        allowed = root / "skills/skill-query-interpreter/output"
        path = Path(raw_input)
        if not path.is_absolute():
            path = root / path
        if not raw_input.strip() or not path.is_relative_to(allowed) or path.resolve() != path:
            raise _Failure("invalid_input", "Provide a path within skills/skill-query-interpreter/output/.")
        _regular(path, "invalid_input")
        if path.suffix != ".md" or not re.fullmatch(r"[0-9a-f]{64}", path.stem):
            raise _Failure("invalid_input", "Expected a Markdown requirement with a 64-hex page ID filename.")
        phase = "invalid_requirement"
        with path.open(encoding="utf-8", newline="") as source:
            text = source.read()
        intent = _intent(text)
        domain_rows = _table(text, "Websites/Domains", ("Websites", "Potential contribution"))
        keyword_rows = _table(text, "Keywords", ("Concept", "Candidate keywords"))
        entity_rows = _table(text, "Entities", ("Entity or slot", "Type", "Interpretation"))
        entities = list(dict.fromkeys(row[0] for row in entity_rows))
        domains = list(dict.fromkeys(d.strip() for row in domain_rows for d in row[0].split(",")))
        keywords = list(dict.fromkeys(k.strip() for row in keyword_rows for k in row[1].split(",")))
        if any(not re.fullmatch(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}", d) for d in domains) or not all(keywords):
            raise _Failure("invalid_requirement", "Expected bare domains and nonempty keyword phrases.")
        phase = "corpus_error"
        corpus = root / "data/bookmark"
        if corpus.resolve() != corpus or not corpus.is_dir():
            raise _Failure("corpus_error", "Bookmark root must be a real directory.")
        found, missing, seen = {}, [], set()
        bookmark_fields = {}
        scanned = matched = 0
        for domain in domains:
            stem = domain.casefold().removeprefix("www.").replace(".", "_")
            folders = [corpus / name for name in (stem, "www_" + stem)
                       if (corpus / name).exists() or (corpus / name).is_symlink()]
            if not folders:
                missing.append(domain)
            for folder in folders:
                if folder.resolve() != folder or not folder.is_dir():
                    raise _Failure("corpus_error", "Domain folders must be real directories.")
                for base, dirs, files in os.walk(folder, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
                    for name in dirs:
                        if (Path(base) / name).is_symlink():
                            raise _Failure("corpus_error", "Bookmark directory symlinks are forbidden.")
                    for name in sorted(files):
                        source = Path(base) / name
                        if source in seen:
                            continue
                        seen.add(source)
                        _regular(source, "corpus_error")
                        source_text = source.read_text(encoding="utf-8")
                        content = _normalize(source_text)
                        if source.name == "bookmark.md":
                            bookmark_fields[source.parent.name] = source_text
                        scanned += 1
                        matches = [k for k in keywords if _normalize(k) in content]
                        entity_matches = [e for e in entities if _normalize(e) in content]
                        if matches or entity_matches:
                            page_id = source.parent.name
                            if not re.fullmatch(r"[0-9a-f]{64}", page_id):
                                raise _Failure("corpus_error", "A matching file lacks a valid parent page ID.")
                            matched += 1
                            entry = found.setdefault(page_id, {"keywords": set(), "entities": set()})
                            entry["keywords"].update(matches)
                            entry["entities"].update(entity_matches)
        payload = [{"page_id": pid,
                    "keywords": [k for k in keywords if k in found[pid]["keywords"]],
                    "entities": [e for e in entities if e in found[pid]["entities"]]}
                   for pid in sorted(found)]
        page_entities = {}
        for page in payload:
            bookmark = bookmark_fields.get(page["page_id"])
            if bookmark is None:
                raise _Failure("corpus_error", "Matched page is missing bookmark.md.")
            page["url"], page_entities[page["page_id"]] = _bookmark_fields(bookmark)
        report, utterance_metadata = _render(payload, page_entities, root, entity_match, fuzzy_threshold)
        report = intent + ("" if intent.endswith("\n\n") else "\n\n") + report
        result["output"] = _write_output(report, path.stem)
        result.update(status="ok", meta_data={"page_id": path.stem, "scanned_files": scanned,
                                             "matched_files": matched, "missing_domains": missing,
                                             **utterance_metadata})
    except _Failure as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    except (OSError, UnicodeError, ValueError) as exc:
        result["error"] = {"code": phase, "message": "Cannot read or validate search sources: " + str(exc)}
    return result


def _write_output(content: str, page_id: str) -> str:
    """Atomically replace <page_id>.md using a pinned tool-local directory."""
    # Resolve output relative to this module, never the caller working directory.
    tool_root = Path(__file__).resolve().parent
    if re.fullmatch(r"[0-9a-f]{64}", page_id) is None:
        raise _Failure("output_write_error", "Output page_id is missing or invalid.")
    filename = f"{page_id}.md"
    descriptor = None
    temporary = None
    try:
        # Pin the directory without following symlinks. Exclusive temporary
        # creation plus flush/fsync/replace preserves an old result on failure.
        # Same-ID concurrent writes are last-replacement-wins; abrupt termination
        # can leave a temporary file for later cleanup.
        descriptor = os.open(tool_root / "output", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        name = f".output-{uuid.uuid4().hex}.tmp"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=descriptor)
        temporary = name
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = None
        return f"{tool_root.name}/output/{filename}"
    except OSError as exc:
        raise _Failure("output_write_error", "Could not save <page_id>.md in the tool output directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)
