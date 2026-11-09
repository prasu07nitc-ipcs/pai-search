"""Fetch Open Graph properties, keywords, and dates."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Literal, TypedDict

from webpage_http import WebpageError, download_html


class CrawlError(TypedDict):
    code: str
    message: str


_PROPERTIES = ("og:title", "og:description", "og:image", "og:url", "og:site_name", "og:type", "article:section")
# Explicit date labels only: separator/case variants are normalized, not inferred.
_DATE_LABELS = {
    "datePublished": {
        "datepublished", "published", "publisheddate", "publishedtime",
        "publishedat", "publishdate", "publishtime", "publicationdate",
        "publicationtime", "pubdate", "dtpublished", "originalpublicationdate",
        "articlepublished", "articlepublisheddate", "articlepublishedtime",
        "articlepublicationdate", "ogarticlepublished", "ogarticlepublishedtime",
        "ogdatepublished", "ogpubdate", "ogpublishdate", "ogpublishedtime",
        "rnewsdatepublished", "citationpublicationdate", "dcdateissued",
        "dcdatepublication", "dctermsissued", "dcissued",
        "dcsextarticlefirstpublished", "parselypubdate", "btpubdate",
        "shareaholicarticlepublishedtime", "mediatorpublishedtime",
        "cxenseparserecspublishtime", "twtpublishedat", "vrpublishedtime",
    },
    "dateModified": {
        "dtupdated", "datemodified", "dateupdated", "dateupdate", "modified", "updated",
        "modifieddate", "modifiedtime", "modifiedat", "updateddate",
        "updatedtime", "updatedat", "updatedate", "updatetime",
        "lastmodified", "lastmodifieddate", "lastmodifiedtime", "lastmod",
        "lastupdated", "lastupdateddate", "lastupdatedtime", "lastupdate",
        "modificationdate", "modificationtime", "revisiondate",
        "articlemodified", "articlemodifieddate", "articlemodifiedtime",
        "articlepostmodified", "articleupdatedtime", "ogarticlemodifiedtime",
        "ogmodifiedtime", "ogupdatedtime", "ogdatemodified",
        "dcmodified", "dcdatemodified", "dctermsmodified",
        "rnewsdatemodified", "btmoddate",
    },
}
_DATE_FIELDS = {label: field for field, labels in _DATE_LABELS.items() for label in labels}


def _date_field(label: str) -> str | None:
    # Schema.org URLs/CURIEs use the same local names as plain microdata keys.
    label = label.strip().lower()
    for prefix in ("https://schema.org/", "http://schema.org/", "schema:"):
        if label.startswith(prefix):
            label = label[len(prefix):]
            break
    return _DATE_FIELDS.get(re.sub(r"[\s:._-]+", "", label))


def _normalize_date(value: str | None) -> tuple[str | None, dict]:
    """Normalize explicit dates without guessing ambiguous numeric order."""
    info = {"raw_value": value, "status": "missing", "assumptions": []}
    if value is None:
        return None, info
    text = value.strip()
    info["status"] = "invalid"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            day = date.fromisoformat(text)
        elif re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}", text):
            first, second, year = map(int, re.split(r"[-/]", text))
            if 1 <= first <= 12 and 1 <= second <= 12 and first != second:
                info["status"] = "ambiguous"
                return None, info
            month, day_number = (second, first) if first > 12 else (first, second)
            day = date(year, month, day_number)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?", text):
            offset = re.search(r"[+-](\d{2}):(\d{2})$", text)
            if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                return None, info
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                info["status"] = "preserved" if "T" in text else "normalized"
                return text if "T" in text else stamp.isoformat(), info
            info.update(status="normalized", assumptions=["timezone_utc"])
            return stamp.replace(tzinfo=timezone.utc).isoformat(), info
        else:
            day = None
            for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
                try:
                    day = datetime.strptime(text, pattern).date()
                    break
                except ValueError:
                    pass
            if day is None:
                # RFC 2822 timestamps must explicitly provide an offset or UTC/GMT.
                if not re.search(r"(?:[+-]\d{4}|UTC|GMT)$", text):
                    return None, info
                offset = re.search(r"[+-](\d{2})(\d{2})$", text)
                if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                    return None, info
                stamp = parsedate_to_datetime(text)
                if stamp.tzinfo is None:
                    return None, info
                info["status"] = "normalized"
                return stamp.isoformat(), info
        info.update(status="normalized", assumptions=["time_midnight", "timezone_utc"])
        return datetime.combine(day, datetime.min.time(), timezone.utc).isoformat(), info
    except (ValueError, TypeError, OverflowError):
        return None, info


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str | None] = dict.fromkeys(_PROPERTIES)
        self.metadata: dict[str, str | None] = dict.fromkeys(
            ("keywords", "datePublished", "dateModified")
        )
        self._jsonld: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if (tag == "script" and (attributes.get("type") or "").lower().strip() == "application/ld+json"
                and not all(self.metadata.values())):
            self._jsonld = []
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            value = (attributes.get("content") or "").strip()
            if key in self.values and value and self.values[key] is None:
                self.values[key] = value
            metadata_key = (key or attributes.get("itemprop") or "").lower()
            if metadata_key == "keywords" and value and self.metadata["keywords"] is None:
                self.metadata["keywords"] = value
        else:
            value = (attributes.get("content") or attributes.get("datetime") or "").strip()
        if not value or (self.metadata["datePublished"] and self.metadata["dateModified"]):
            return
        # Inspect every semantic attribute so an unrelated name cannot hide itemprop.
        # A time element may additionally label its datetime using class/id tokens.
        for attribute in ("property", "name", "itemprop", "http-equiv"):
            label = attributes.get(attribute) or ""
            labels = label.split() if attribute in ("property", "itemprop") else [label]
            for item in labels:
                field = _date_field(item)
                if field and self.metadata[field] is None:
                    self.metadata[field] = value
        if tag == "time":
            for label in ((attributes.get("class") or "").split() + [attributes.get("id") or ""]):
                field = _date_field(label)
                if field and self.metadata[field] is None:
                    self.metadata[field] = value

    def handle_data(self, data):
        if self._jsonld is not None:
            self._jsonld.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or self._jsonld is None:
            return
        source = "".join(self._jsonld)
        self._jsonld = None
        try:
            document = json.loads(source)
        except (ValueError, RecursionError):
            return
        pending = [document]
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(reversed(node))
            elif isinstance(node, dict):
                for key, value in node.items():
                    field = "keywords" if key == "keywords" else _date_field(key)
                    if not field:
                        continue
                    if field == "keywords" and isinstance(value, list):
                        value = ", ".join(item.strip() for item in value if isinstance(item, str) and item.strip())
                    if isinstance(value, str) and value.strip() and self.metadata[field] is None:
                        self.metadata[field] = value.strip()
                # Follow article/page relationships, not author/review/product dates.
                children = [node[key] for key in ("@graph", "mainEntity", "mainEntityOfPage") if key in node]
                pending.extend(reversed(children))

    handle_startendtag = handle_starttag


class CrawlInput(TypedDict):
    page_id: str
    processed_input: dict[str, str]


class CrawlResult(TypedDict):
    input: CrawlInput
    output: str | None
    output_format: str
    status: Literal["ok", "error"]
    error: CrawlError | None
    meta_data: dict


def crawl_open_graph(url: str, page_id: str) -> CrawlResult:
    """Fetch metadata for a public URL, preserving its validated input identity.

    page_id must be the lowercase SHA-256 hexadecimal digest of the exact input URL.
    Uses the shared URL constraints and 15-second network budget.
    Success atomically replaces tool-local output/<page_id>.json with UTF-8 JSON text.
    Expected fetch/write failures return output=null and a structured error.
    """
    result: CrawlResult = {
        "input": {"page_id": page_id, "processed_input": {"url": url}},
        "output": None, "output_format": "json", "status": "error", "error": None,
        "meta_data": {"requested_url": url, "final_url": None, "date_normalization": {}},
    }
    if not re.fullmatch(r"[0-9a-f]{64}", page_id) or page_id != hashlib.sha256(url.encode("utf-8")).hexdigest():
        result["error"] = {"code": "invalid_page_id", "message": "page_id must equal the lowercase SHA-256 digest of the supplied URL."}
        return result
    payload = download_html(url)
    result["meta_data"]["final_url"] = payload["final_url"]
    if payload["status"] == "error":
        result["error"] = payload["error"]
        return result
    parser = _Parser()
    parser.feed(payload["html"])
    parser.close()
    content = {key.split(":", 1)[-1]: item for key, item in parser.values.items()}
    content.update(parser.metadata)
    content["requested_url"] = url
    for field in ("datePublished", "dateModified"):
        content[field], info = _normalize_date(content[field])
        result["meta_data"]["date_normalization"][field] = info
    content["page_id"] = page_id
    try:
        path = _write_output(json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2) + "\n", page_id)
        result.update(status="ok", output=path)
    except WebpageError as exc:
        result["error"] = {"code": exc.code, "message": str(exc)}
    return result


def _write_output(content: str, page_id: str) -> str:
    """Atomically replace <page_id>.json using a pinned tool-local directory."""
    # Resolve output relative to this module, never the caller working directory.
    tool_root = Path(__file__).resolve().parent
    if re.fullmatch(r"[0-9a-f]{64}", page_id) is None:
        raise WebpageError("output_write_error", "Output page_id is missing or invalid.")
    filename = f"{page_id}.json"
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
        raise WebpageError("output_write_error", "Could not save <page_id>.json in the tool output directory.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except OSError:
                pass
        if descriptor is not None:
            os.close(descriptor)
