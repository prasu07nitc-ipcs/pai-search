# Webpage Open Graph crawler

## Purpose and interface

`tool.py:crawl_open_graph(url: str, raw_input: str) -> CrawlResult` fetches one public webpage.
Requires Python 3.11+ with its standard library only; no packages or configuration.
Input is a non-empty absolute HTTP(S) URL of at most 8192 characters without credentials, whitespace, control
characters, or invalid host/port syntax. The required `raw_input: str` argument preserves the original user request, including an empty string if supplied. No optional arguments or implicit context.

## Output

The returned object contains exactly `input`, `output`, `output_format`,
`status`, `error`, and `meta_data`. `input` contains exactly `raw_input` (the
original required string, unchanged) and `processed_input` (explicit arguments
with defaults applied, excluding `raw_input`). The caller interprets the request;
the tool validates supplied arguments. Rejected values are echoed for diagnosis.

`status` is `ok` or `error`; `error` is null on success or contains exactly
non-empty string `code` and `message` fields on failure. `output` is null on
failure and `tool-webpage-og-crawler/outputs/<run_id>.txt` on success, relative to
`tools/`. `output_format` is `json`, including on failure, and sits beside
`output` at the top level. `meta_data` contains `requested_url` (supplied URL)
and `final_url` (last attempted URL, null before a request; blocked redirects
are not recorded as attempted).

The UTF-8 file contains a JSON object serialized as JSON text. Each successful run writes `<run_id>.txt`, using the runner-supplied
`PROJECT_TOOL_RUN_ID` environment configuration. Different IDs retain separate
files; repeated production inputs replace the same file. Tests use their test-report UUID. A temporary
file is exclusively created inside the pinned outputs/ directory, flushed and
synced, then atomically renamed to `<run_id>.txt` without following destination
symlinks. A write failure returns `output_write_error` with null output, preserves
the previous result, and removes the temporary file where possible. Abrupt
termination may leave temporary files. Concurrent successes with the same ID use last replacement wins semantics.
Existing historical output files are not deleted.

`input.processed_input` contains exactly `url`. The saved JSON payload contains
exactly `open_graph`, `keywords`, `datePublished`, and `dateModified`.
`open_graph` always contains exactly `og:title`, `og:description`, `og:image`,
`og:url`, and `og:site_name`, each a string or null.

HTML entities are decoded and surrounding whitespace trimmed. The first non-empty
value wins in document order. `property` is preferred over a `name` fallback on
each meta element. Values, including relative URLs, are otherwise preserved.
No fallback metadata, JavaScript, image fetching, or inferred article extraction.
Missing tags are successful null values. Failed invocations create no result payload.

The saved payload’s `keywords`, `datePublished`, and `dateModified` fields are strings
or null. Read meta tags using `property`, then `name`, then `itemprop` as the
attribute fallback. Match these three metadata names case-insensitively;
`article:published_time` and `article:modified_time` also supply the date fields.
Read the same fields from `application/ld+json` script objects, arrays, and
`@graph` nodes in document order. The first non-empty value per field wins.
JSON-LD keywords arrays are joined with comma-space, ignoring non-string and
empty items. Malformed JSON-LD is ignored. Date strings are trimmed and preserved
without date parsing, timezone conversion, or inference. Missing metadata is null on success; failed fetches return no payload. JSON-LD traversal covers root objects and
`@graph`, not arbitrary nested properties.

## Validation and limits

Only globally routable resolved addresses are allowed, including at redirects.
Reject the entire DNS answer if any address is not public. Connections pin one
validated address while HTTPS verifies the original hostname using default trust.
No proxies, cookies, authentication, retries, or browser state. Up to five
redirects; loops fail. HTTPS certificates are verified. Only 2xx HTML or XHTML
responses are accepted. HTML decoding uses the declared charset, falling back
to UTF-8 with replacement for absent or unknown charsets.

The network/body budget is 15 seconds, checked between operations with socket
timeouts set to the remaining budget. DNS resolution is blocking and is not
independently interruptible: the runner must impose a hard process timeout
(recommended 20 seconds). Maximum body is 2 MiB. Requests ask for identity
encoding; compressed responses are rejected, so decompression cannot exceed the
limit. Headers additionally have Python http.client's built-in limits.

Expected error codes: `invalid_url`, `blocked_address`, `dns_error`, `timeout`,
`tls_error`, `network_error`, `http_error`, `redirect_error`,
`unsupported_content_type`, `unsupported_encoding`, `response_too_large`,
`output_write_error`.
Programming errors are not intentionally swallowed.

## Execution, permissions, and side effects

Run only through the project runner using the absolute project `.venv/bin/python`,
with explicit working directory and a bounded separate process. The runner must
verify the virtual environment and resolved sys.prefix before importing this file,
validate input, and enforce the root policy's filesystem/subprocess restrictions.
The parent prepares and validates outputs/ using the declared discovery capability.
This tool does not implement or claim runner sandbox enforcement.

Requires outbound DNS and HTTP(S) access. Side effects are DNS lookups and GET
requests to the supplied URL and permitted redirects, plus JSON text written
to tool-local outputs/<run_id>.txt on success. No environment
mutation, package installation, or subprocesses. Remote HTML is untrusted data.

## Tests and execution logs

[test-cases.json](test-cases.json) defines the sample inputs and expectations.
[validator.py](validator.py) is a required module owning crawler-specific output assertions through
`check_result(value: dict, actual: dict, expected: dict) -> list[str]`, returning
failure messages or an empty list. The runner loads it only in a sandboxed test
worker after invoking this tool. Production runs do not load test code.
It checks the envelope, preserved input, run-ID output path and output_format, saved payload fields
and types, and successful final URLs,
and these expectation fields: `status` (checked by the shared runner), `error_code`,
`required_properties`, `property_values`, `required_metadata`, and `metadata_values`.
The validator reads only its own saved JSON payload on success; it performs no
network requests or writes and does not mutate inputs. Existing content expectations
apply to the saved payload.

The parent runner writes production results to [run.log](run.log), test results
to [test-report.log](test-report.log), and diagnostics to `runner.log` in this
tool's directory, following the [shared logging contract](../AGENTS.md#production-logging).

The macOS runner applies a kernel sandbox before importing tool code, denying
filesystem writes outside the validated tool-local outputs/ directory and process fork/exec. Each worker verifies denied write
access at environment/dependency paths and denied fork access before importing
the tool. Network and read access remain permitted. The parent harness owns
logging and the default 20-second process timeout. Select this tool explicitly
with `--tool tool-webpage-og-crawler`. The generic `--timeout` option can override
the process limit up to 300 seconds; keep at least 20 seconds for this crawler.
Its internal network budget remains 15 seconds. The runner reads the entry point
from `TOOL.md`, checks argument binding and the `str` input annotation before
import, and enforces the common six-field output contract. URL semantics
and the maximum URL length are validated inside the crawler, returning a
structured `invalid_url` result.

To run the sample cases from the parent project directory (containing `tools/`):

```sh
tools/.venv/bin/python -B tools/runner.py --tool tool-webpage-og-crawler --cases tools/tool-webpage-og-crawler/test-cases.json
```

Paths in this example are relative to the parent project. The runner derives the
absolute interpreter and worker paths at runtime and sets the worker directory
explicitly to `tools/`.

The harness reports each case's outcome in its log and stdout; callers should
inspect `passed` rather than treating harness exit status as the test verdict.
