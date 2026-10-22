"""Transaction runner with exclusive data ownership and isolated tests (macOS, Python 3.11+).

STRICT dependency policy: runner infrastructure must use only Python built-ins
and the standard library. No third-party, optional, vendored, or indirect Python
dependencies. See transactions/AGENTS.md for the authoritative policy.
"""
from __future__ import annotations
from zoneinfo import ZoneInfo

import argparse
import base64
import ast
import contextlib
import inspect
import math
import re
import types
import typing
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import tempfile
import stat
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime, timezone
from functools import wraps

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DATA = PROJECT / "data"
ENV = ROOT / ".venv"
PYTHON = ENV / "bin/python"
LOGGER = logging.getLogger(__name__)


def canonical_hash(value):
    """Stable JSON identity; preserve the production run-ID byte contract."""
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def owned_data_name(transaction_name):
    """Runner-owned mapping; transaction definitions cannot choose destinations."""
    if transaction_name == "tx-articles":
        raise ValueError("data/articles/ is exclusively reserved for tx-publish-article.")
    return "articles" if transaction_name == "tx-publish-article" else transaction_name[3:]


def repository_http_url(remote):
    """Return a credential-free HTTP remote, normalizing SSH remotes."""
    if re.match(r"^[^/@:]+@[^/:]+:.+", remote):
        host, path = remote.split("@", 1)[1].split(":", 1)
        remote = "https://" + host + "/" + path
    try:
        parsed = urlsplit(remote)
        if parsed.scheme not in ("http", "https", "ssh") or not parsed.hostname:
            return "Unavailable"
        host = parsed.hostname
        if ":" in host:
            host = "[" + host + "]"
        if parsed.scheme != "ssh" and parsed.port:
            host += ":" + str(parsed.port)
        path = parsed.path.removesuffix(".git")
        return urlunsplit(("https" if parsed.scheme == "ssh" else parsed.scheme, host, path, "", ""))
    except ValueError:
        return "Unavailable"


def source_code_signature(directory):
    """Snapshot Git metadata for the selected transaction before worker launch."""
    def git(*args, input=None, allowed=(0,)):
        result = subprocess.run(["git", "-C", str(directory), *args], input=input,
                                capture_output=True, text=True, timeout=5,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        if result.returncode not in allowed:
            raise ValueError("Git signature capture failed.")
        return result.stdout

    signature = {"repository_url": "Unavailable", "branch": "Unavailable",
                 "commit": "Unavailable", "local_changes": []}
    try:
        root = Path(git("rev-parse", "--show-toplevel").strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return signature
    # Fail on incomplete snapshots in a Git repository rather than report it clean.
    signature["repository_url"] = repository_http_url(git("config", "--get", "remote.origin.url", allowed=(0, 1)).strip())
    signature["commit"] = git("rev-parse", "--verify", "HEAD").strip()
    signature["branch"] = git("symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1)).strip() or "Detached HEAD"
    relative = directory.relative_to(root).as_posix()
    records = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--", ":(top,literal)" + relative).split("\0")
    changes = [(record[:2], record[3:]) for record in records if record]
    if changes:
        # --no-index also excludes tracked files newly matched by ignore rules.
        ignored = set(git("-C", str(root), "check-ignore", "--no-index", "-z", "--stdin",
                          input="\0".join(path for _, path in changes) + "\0", allowed=(0, 1)).split("\0"))
        signature["local_changes"] = [{"status": status, "path": path} for status, path in changes if path not in ignored]
    return signature


def signature_markdown(signature):
    """Render the runner-owned snapshot consistently for every transaction."""
    def escaped(value):
        return re.sub(r"([\\`*_{}\[\]<>#+|])", r"\\\1", " ".join(value.split()))
    lines = ["## Source Code Signature", "",
             "- Git repository URL: " + escaped(signature["repository_url"]),
             "- Git branch: " + escaped(signature["branch"]),
             "- Git commit: " + escaped(signature["commit"])]
    if signature["local_changes"]:
        lines += ["- Local changes:"] + ["  - " + escaped(c["status"].replace(" ", "."))
                                        + ": " + escaped(c["path"]) for c in signature["local_changes"]]
    else:
        lines.append("- Local changes: None")
    return "\n".join(lines) + "\n"


def logs_directory(directory):
    """Prepare runner-owned logs without following directory or file symlinks."""
    target = directory / "logs"
    if target.is_symlink():
        raise ValueError("Logs directory must not be a symlink")
    target.mkdir(exist_ok=True)
    for name in ("run.log", "runner.log", "test-report.log", "index.lock", "index-attempts.jsonl"):
        path = target / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
            raise ValueError("Logs must be regular, unlinked files")
    return target


class DuplicateInputError(ValueError):
    """A previous production execution requires explicit rerun confirmation."""


@contextlib.contextmanager
def production_history(directory):
    """Read history under a shared lock without creating a result log."""
    try:
        history = (directory / "logs" / "run.log").open("r", encoding="utf-8")
    except FileNotFoundError:
        yield ()
        return
    with history:
        fcntl.flock(history, fcntl.LOCK_SH)
        yield history


def require_new_input(directory, input_id):
    """Check successful production history, including records lacking run_id."""
    with production_history(directory) as history:
        for line in history:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("status") != "ok":
                continue
            supplied = dict(record["processed_input"])
            supplied["raw_input"] = record["raw_input"]
            previous_id = canonical_hash(supplied)
            if previous_id == input_id:
                raise DuplicateInputError(
                    f"Input already executed for {directory.name} (run_id {input_id}). "
                    "Ask the user to confirm a rerun, then pass --rerun."
                )


def log_execution(function):
    """Log each call and its elapsed time without changing its result or errors."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        LOGGER.info("Function %s started", function.__qualname__)
        try:
            result = function(*args, **kwargs)
        except BaseException:
            LOGGER.exception(
                "Function %s failed; total execution time: %.6f seconds",
                function.__qualname__, time.perf_counter() - started,
            )
            raise
        LOGGER.info(
            "Function %s completed; total execution time: %.6f seconds",
            function.__qualname__, time.perf_counter() - started,
        )
        return result
    return wrapped


@log_execution
def verify_environment():
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != ENV.resolve():
        raise RuntimeError(f"Run with {PYTHON}; the project virtual environment is required.")


@log_execution
def resolve_transaction(name):
    if not isinstance(name, str) or len(name) >= 64 or not re.fullmatch(r"tx-[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Select a transaction using its tx-<name> folder name.")
    directory = ROOT / name
    if directory.is_symlink() or directory.resolve().parent != ROOT:
        raise ValueError("Transaction must be a direct, non-symlink project directory.")
    for filename in ("TRANSACTION.md", "AGENTS.md", "transaction.py", "validator.py"):
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular transaction file: {filename}")
    discovery = (directory / "TRANSACTION.md").read_text(encoding="utf-8")
    if discovery.lstrip().startswith("---"):
        raise ValueError("TRANSACTION.md must not contain YAML frontmatter.")
    if not re.search(rf"^Name: {re.escape(name)}\s*$", discovery, re.M):
        raise ValueError("TRANSACTION.md Name must match the transaction directory.")
    if not re.search(r"^Description: \S.+$", discovery, re.M):
        raise ValueError("TRANSACTION.md must declare a Description.")
    if not re.search(r"^Instructions: \[AGENTS\.md\]\(AGENTS\.md\)\s*$", discovery, re.M):
        raise ValueError("TRANSACTION.md must link to AGENTS.md.")
    entry = re.search(r"^Entry point: `transaction\.py:([A-Za-z_]\w*)", discovery, re.M)
    if entry is None or entry[1].startswith("_"):
        raise ValueError("TRANSACTION.md must declare a public transaction.py function entry point.")
    if not re.search(rf"^Data directory: data/{re.escape(owned_data_name(name))}/\s*$", discovery, re.M):
        raise ValueError("Data directory must match the transaction name convention.")
    validator_tree = ast.parse((directory / "validator.py").read_text(encoding="utf-8"))
    checker = next((node for node in validator_tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "check_result"), None)
    if (checker is None or checker.args.posonlyargs or checker.args.kwonlyargs
            or checker.args.vararg or checker.args.kwarg or checker.args.defaults
            or [argument.arg for argument in checker.args.args] != ["value", "actual", "expected"]
            or any(argument.annotation is None or ast.unparse(argument.annotation) != "dict"
                   for argument in checker.args.args)
            or checker.returns is None or ast.unparse(checker.returns) != "list[str]"):
        raise ValueError("validator.py must define check_result(value: dict, actual: dict, expected: dict) -> list[str].")
    return directory, entry[1]


@log_execution
def validate_input(directory, entry, value):
    """Bind JSON arguments against the source signature without importing transaction code."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Input must be a JSON object of named arguments.")
    if not isinstance(value.get("raw_input"), str):
        raise ValueError("raw_input is a required string.")
    json.dumps(value, allow_nan=False)
    tree = ast.parse((directory / "transaction.py").read_text(encoding="utf-8"))
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == entry), None)
    if function is None:
        raise ValueError("Entry point must be a top-level synchronous function.")
    arguments = function.args
    if arguments.posonlyargs or arguments.vararg or arguments.kwarg:
        raise ValueError("Transaction entry points must declare explicit named parameters.")
    parameters = []
    positional = arguments.args
    required = len(positional) - len(arguments.defaults)
    for index, argument in enumerate(positional):
        default = inspect.Parameter.empty if index < required else None
        parameters.append(inspect.Parameter(argument.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default))
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        parameters.append(inspect.Parameter(argument.arg, inspect.Parameter.KEYWORD_ONLY,
                                            default=inspect.Parameter.empty if default is None else None))
    inspect.Signature(parameters).bind(**value)
    # Primitive annotations can also be checked safely before any import.
    primitives = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
    for argument in positional + arguments.kwonlyargs:
        if argument.annotation is None:
            raise ValueError(f"Parameter {argument.arg} must have an explicit type annotation.")
        if argument.arg in value and isinstance(argument.annotation, ast.Name) and argument.annotation.id in primitives:
            if not matches_type(value[argument.arg], primitives[argument.annotation.id]):
                raise ValueError(f"Incorrect type for argument {argument.arg}.")
    if function.returns is None:
        raise ValueError("Transaction entry points must declare their return type.")


@log_execution
def matches_type(value, annotation):
    """Time one type-validation operation rather than logging every nested value."""
    return _matches_type(value, annotation)


def _matches_type(value, annotation):
    """Validate supported JSON-compatible Python annotations without coercion."""
    if annotation is typing.Any:
        return True
    if annotation is None or annotation is type(None):
        return value is None
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(_matches_type(value, item) for item in args)
    if origin is typing.Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if typing.is_typeddict(annotation):
        hints = typing.get_type_hints(annotation)
        return (isinstance(value, dict) and annotation.__required_keys__ <= value.keys()
                and value.keys() <= hints.keys()
                and all(_matches_type(item, hints[key]) for key, item in value.items()))
    if origin is list:
        return isinstance(value, list) and all(_matches_type(item, args[0]) for item in value)
    if origin is dict:
        return isinstance(value, dict) and all(_matches_type(key, args[0]) and _matches_type(item, args[1]) for key, item in value.items())
    if annotation in (str, bool, int, list, dict):
        return type(value) is annotation
    if annotation is float:
        return type(value) in (int, float) and math.isfinite(value)
    raise ValueError(f"Unsupported transaction input annotation: {annotation!r}")


@log_execution
def validate_output(result, transaction_name=None, run_id=None):
    if not isinstance(result, dict) or result.get("status") not in ("ok", "error") or "error" not in result:
        raise ValueError("Transaction output must be an object with status ('ok'/'error') and error.")
    if set(result) != {"input", "output", "output_format", "status", "error", "meta_data"}:
        raise ValueError("Transaction result requires exactly input, output, output_format, status, error, and meta_data.")
    inputs = result["input"]
    if (not isinstance(inputs, dict) or set(inputs) != {"raw_input", "processed_input"}
            or not isinstance(inputs["raw_input"], str) or not isinstance(inputs["processed_input"], dict)):
        raise ValueError("input requires raw_input string and processed_input object.")
    if not isinstance(result["meta_data"], dict):
        raise ValueError("meta_data must be an object.")
    if not isinstance(result.get("output_format"), str) or not result["output_format"].strip():
        raise ValueError("output_format must be a non-empty string.")
    output = result["output"]
    if result["status"] == "ok":
        if not isinstance(transaction_name, str) or not re.fullmatch(r"tx-[a-z0-9]+(?:-[a-z0-9]+)*", transaction_name):
            raise ValueError("Selected transaction required for output validation.")
        prefix = f"data/{owned_data_name(transaction_name)}/"
        if not isinstance(output, list) or not output:
            raise ValueError("Successful output must be a nonempty array of file paths.")
        for path in output:
            if (not isinstance(path, str) or not path.startswith(prefix)
                    or (transaction_name != "tx-index" and ("\\" in path or any(ord(c) < 32 for c in path)))
                    or any(part in ("", ".", "..") for part in path.split("/"))):
                raise ValueError("Output paths must be canonical files in the owned data directory.")
        if len(set(output)) != len(output):
            raise ValueError("Output paths must be unique.")
    elif output is not None:
        raise ValueError("Failed transaction output must be null.")
    error = result["error"]
    if result["status"] == "ok":
        if error is not None:
            raise ValueError("Successful transaction output must have error=null.")
    elif (not isinstance(error, dict) or set(error) != {"code", "message"}
          or any(not isinstance(error[key], str) or not error[key] for key in ("code", "message"))):
        raise ValueError("Failed transaction output requires non-empty error.code and error.message strings.")
    json.dumps(result, allow_nan=False)


@log_execution
def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_tree(target):
    """Reject filesystem aliases before granting the selected write subtree."""
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("Data directory must be a real directory.")
    if target.exists():
        for base, directories, files in os.walk(target, followlinks=False):
            for name in directories + files:
                item = Path(base) / name
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and
                        (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                    raise ValueError("Data aliases and non-regular files are forbidden.")
    return target


def prepare_data(transaction_name, data_root):
    # Parent-only operation, after pre-execution validation and rerun checks.
    if data_root.is_symlink() or data_root.resolve() != data_root:
        raise ValueError("Data root must be canonical and not a symlink.")
    data_root.mkdir(exist_ok=True)
    target = data_root / owned_data_name(transaction_name)
    validate_tree(target)
    target.mkdir(exist_ok=True)
    return validate_tree(target)


def validate_saved_output(result, transaction_name, destination):
    if result["status"] != "ok":
        return
    validate_tree(destination)
    for output in result["output"]:
        relative = Path(output).relative_to(Path("data") / owned_data_name(transaction_name))
        target = destination / relative
        if not target.is_file() or target.is_symlink() or target.stat().st_nlink != 1:
            raise ValueError("Successful output must identify existing regular owned data files.")


@log_execution
def worker(transaction_name, value, expected=None, run_id=None, data_directory=None, test_run=False, source_signature=None, input_directory=None, index_batch=None):
    verify_environment()
    directory, entry = resolve_transaction(transaction_name)
    validate_input(directory, entry, value)
    if sys.platform != "darwin":
        raise RuntimeError("This runner requires macOS sandbox_init; refusing unsandboxed execution.")
    if not isinstance(data_directory, str):
        raise ValueError("Parent must supply the prepared data directory.")
    outputs = Path(data_directory)
    if (not outputs.is_absolute() or outputs.resolve() != outputs or
            outputs.name != owned_data_name(transaction_name) or not outputs.is_dir()):
        raise ValueError("Invalid prepared data directory.")
    if test_run:
        temporary_root = outputs.parent.parent
        if (outputs.parent.name != "data" or temporary_root.parent != Path(tempfile.gettempdir()).resolve()
                or not temporary_root.name.startswith("transaction-test-")):
            raise ValueError("Test worker destination must be an isolated runner temporary directory.")
    elif outputs != DATA / owned_data_name(transaction_name):
        raise ValueError("Production worker destination must match the repository data convention.")
    validate_tree(outputs)
    # Install a kernel-enforced sandbox before importing transaction code.
    library = ctypes.CDLL("/usr/lib/libsandbox.dylib", use_errno=True)
    library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    library.sandbox_init.restype = ctypes.c_int
    error = ctypes.c_char_p()
    readable = [directory, outputs, ENV.resolve(), Path(sys.base_prefix).resolve(),
                Path('/System'), Path('/usr/lib'), Path('/usr/share'),
                Path('/private/etc'), Path('/private/var/run'), Path('/dev'),
                Path('/Library/Apple'), Path('/Library/Preferences/SystemConfiguration')]
    rules = ['(version 1)', '(allow default)', '(deny file-read*)', '(allow file-read-metadata)',
             '(deny file-write*)', '(deny process-fork)', '(deny process-exec)',
             '(deny file-link)']
    for path in readable:
        rules.append('(allow file-read* (subpath ' + json.dumps(str(path)) + '))')
    # Grant each selected transaction only its authorized producer output reads.
    article_input_root = PROJECT
    if test_run:
        if not isinstance(input_directory, str):
            raise ValueError("Parent must supply the isolated fixture root.")
        article_input_root = Path(input_directory)
        if (not article_input_root.is_absolute() or article_input_root.resolve() != article_input_root
                or article_input_root.parent != PROJECT / ".tmp"
                or not article_input_root.name.startswith("transaction-fixtures-")
                or not article_input_root.is_dir()):
            raise ValueError("Test fixture root must be isolated under project .tmp/.")
    elif input_directory is not None:
        raise ValueError("Production cannot override the source input root.")
    source_components = {
        "tx-bookmark": ("tools/tool-webpage-og-crawler",),
        "tx-index": ("tools/tool-webpage-og-crawler", "skills/skill-context-encoder"),
        "tx-publish-article": ("tools/tool-webpage-og-crawler", "skills/skill-article-writer"),
    }
    if transaction_name in source_components:
        for component in source_components[transaction_name]:
            source = article_input_root / component / "output"
            rules.append('(allow file-read* (subpath ' + json.dumps(str(source)) + '))')
    if transaction_name == "tx-index":
        zone_file = Path("/usr/share/zoneinfo/Asia/Kolkata").resolve()
        rules.append('(allow file-read* (literal ' + json.dumps(str(zone_file)) + '))')
    # Bookmark opens each ancestor with O_NOFOLLOW. Permit those directories
    # themselves, without granting reads of sibling subtrees.
    for ancestor in outputs.parents:
        rules.append('(allow file-read* (literal ' + json.dumps(str(ancestor)) + '))')
    rules.append('(allow file-read* (literal ' + json.dumps(str(Path(__file__).resolve())) + '))')
    if outputs is not None:
        rules.append('(allow file-write* (subpath ' + json.dumps(str(outputs)) + '))')
        rules.append('(deny file-write-unlink (literal ' + json.dumps(str(outputs)) + '))')
    profile = ''.join(rules).encode('utf-8')
    if library.sandbox_init(profile, 0, ctypes.byref(error)) != 0:
        raise RuntimeError("Cannot apply transaction sandbox: " + (error.value or b"unknown").decode())
    # Verify the relevant restrictions rather than relying only on profile text.
    for target in (ENV / ".runner-write-probe", ROOT / "requirements.txt", ROOT / "uv.lock",
                   outputs.parent / ".transaction-root-probe",
                   directory / ".transaction-local-probe"):
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except PermissionError:
            pass
        else:
            os.close(descriptor)
            raise RuntimeError("Sandbox write restriction verification failed.")
    try:
        with (ROOT / "AGENTS.md").open("rb") as unrelated:
            unrelated.read(1)
    except PermissionError:
        pass
    else:
        raise RuntimeError("Sandbox read restriction verification failed.")
    try:
        child = os.fork()
    except PermissionError:
        pass
    else:
        if child == 0:
            os._exit(1)
        os.waitpid(child, 0)
        raise RuntimeError("Sandbox process restriction verification failed.")
    if not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", run_id) is None:
        raise ValueError("Invalid execution run_id.")
    os.environ["PROJECT_TRANSACTION_SOURCE_SIGNATURE"] = json.dumps(source_signature)
    os.environ["PROJECT_TRANSACTION_SIGNATURE_MARKDOWN"] = signature_markdown(source_signature)
    os.environ["PROJECT_TRANSACTION_RUN_ID"] = run_id
    os.environ["PROJECT_TRANSACTION_DATA_DIRECTORY"] = str(outputs)
    if transaction_name in source_components:
        os.environ["PROJECT_TRANSACTION_INPUT_ROOT"] = str(article_input_root)
    if transaction_name == "tx-index":
        os.environ["PROJECT_TRANSACTION_TIMEZONE"] = "Asia/Kolkata"
        if index_batch:
            os.environ["PROJECT_TRANSACTION_INDEX_HASHES"] = json.dumps(index_batch["hashes"])
            os.environ["PROJECT_TRANSACTION_INDEXED_AT"] = index_batch["indexed_at"]
    # Keep transaction prints away from the JSON transport on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        module = load_module(directory / "transaction.py", "project_" + transaction_name.replace("-", "_"))
        function = getattr(module, entry)
        signature = inspect.signature(function)
        bound = signature.bind(**value)
        bound.apply_defaults()
        hints = typing.get_type_hints(function)
        for name, argument in bound.arguments.items():
            if name not in hints or not matches_type(argument, hints[name]):
                raise ValueError(f"Incorrect type for argument {name}.")
        result = log_execution(function)(**value)
        validate_output(result, transaction_name, run_id)
        validate_saved_output(result, transaction_name, outputs)
        if result["input"]["raw_input"] != value["raw_input"]:
            raise ValueError("Transaction changed raw_input.")
        failures = []
        if expected is not None:
            if "status" in expected and result["status"] != expected["status"]:
                failures.append("Unexpected status")
            checks = directory / "validator.py"
            if checks.is_symlink() or not checks.is_file():
                raise ValueError("validator.py must be a regular transaction-local file.")
            validator = load_module(checks, "validator_" + transaction_name.replace("-", "_"))
            transaction_failures = log_execution(validator.check_result)(value, result, expected)
            if not isinstance(transaction_failures, list) or any(not isinstance(item, str) for item in transaction_failures):
                raise ValueError("Validator must return a list of failure strings.")
            failures.extend(transaction_failures)
            if any(not isinstance(item, str) for item in failures):
                raise ValueError("Test checks must return a list of failure strings.")
    packet = {"output": result, "failed_checks": failures} if expected is not None else result
    print(json.dumps(packet, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def invoke(transaction_name, value, **options):
    if transaction_name != "tx-index":
        return _invoke(transaction_name, value, **options)
    verify_environment()
    directory, entry = resolve_transaction(transaction_name)
    validate_input(directory, entry, value)
    if options.get("test_run"):
        return _invoke(transaction_name, value, **options)
    timeout = options.get("timeout", 20)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("Timeout must be greater than zero and at most 300 seconds.")
    if options.get("expected") is not None:
        raise ValueError("Test expectations require test_run=True.")
    logs_directory(directory)
    # The parent owns the lock and journal; workers cannot mutate either.
    with (directory / "logs" / "index.lock").open("a") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for tx-index execution lock.")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        sources = []
        for key in ("page_file", "context_file"):
            source = Path(value[key])
            sources.append(str((PROJECT / source).resolve()))
        hashes = []
        for source, component in zip(sources, ("tools/tool-webpage-og-crawler", "skills/skill-context-encoder")):
            path = Path(source)
            original = Path(value["page_file" if not hashes else "context_file"])
            original = PROJECT / original
            if (original != path or '..' in original.parts or path.parent != PROJECT / component / "output"
                    or re.fullmatch(r"[0-9a-f]{64}\.txt", path.name) is None):
                raise ValueError("Invalid index source path.")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Index source must be a regular unaliased file.")
                hashes.append(hashlib.sha256(stream.read()).hexdigest())
        identity = hashlib.sha256(json.dumps(["replacement-v1", hashes]).encode()).hexdigest()
        journal = directory / "logs" / "index-attempts.jsonl"
        previous = None
        if journal.exists():
            for line in journal.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record["identity"] == identity:
                    previous = record
        recovering = previous is not None and previous["state"] in ("started", "failed")
        indexed_at = previous["indexed_at"] if recovering else datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
        index_batch = {"hashes": hashes, "indexed_at": indexed_at}
        def record_state(state):
            with journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"identity": identity, "sources": sources, "state": state, "indexed_at": indexed_at, "version": "replacement-v1"}) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        # Check shared successful-input confirmation before recording an attempt.
        if not options.get("rerun"):
            input_id = canonical_hash(value)
            require_new_input(directory, input_id)
        record_state("started")
        try:
            packet = _invoke(transaction_name, value, index_batch=index_batch, **options)
            record_state("completed" if packet["status"] == "ok" else "failed")
            return packet
        except BaseException:
            record_state("failed")
            raise


@log_execution
def _invoke(transaction_name, value, *, test_run=False, expected=None, timeout=20, run_id=None, rerun=False, fixture_files=None, index_batch=None):
    verify_environment()
    directory, entry = resolve_transaction(transaction_name)
    validate_input(directory, entry, value)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("Timeout must be greater than zero and at most 300 seconds.")
    if fixture_files is not None and not test_run:
        raise ValueError("Fixture files require test_run=True.")
    if expected is not None and not test_run:
        raise ValueError("Test expectations require test_run=True.")
    logs_directory(directory)
    input_id = canonical_hash(value)
    if not test_run and not rerun and index_batch is None:
        log_execution(require_new_input)(directory, input_id)
    isolated = tempfile.TemporaryDirectory(prefix="transaction-test-") if test_run else None
    data_root = Path(isolated.name).resolve() / "data" if isolated else DATA
    run_id = (run_id or str(uuid.uuid4())) if test_run else input_id
    record = {
        "run_id": run_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "processed_input": {key: argument for key, argument in value.items() if key != "raw_input"},
        "raw_input": value["raw_input"], "transaction_input": None,
        "output": None, "output_format": None,
        "status": "error", "error": None, "meta_data": None,
    }
    worker_stderr = None
    fixture_directory = None
    try:
        if test_run:
            temporary_root = PROJECT / ".tmp"
            if temporary_root.is_symlink() or temporary_root.resolve() != temporary_root:
                raise ValueError("Project .tmp must be canonical and not a symlink.")
            temporary_root.mkdir(exist_ok=True)
            fixture_directory = tempfile.TemporaryDirectory(prefix="transaction-fixtures-", dir=temporary_root)
            fixture_root = Path(fixture_directory.name)
            if fixture_files is not None and not isinstance(fixture_files, dict):
                raise ValueError("fixture_files must map relative paths to base64 bytes.")
            for relative, encoded in (fixture_files or {}).items():
                path = Path(relative)
                if (path.is_absolute() or any(part in ("", ".", "..") for part in relative.split("/"))
                        or "\\\\" in relative):
                    raise ValueError("Fixture paths must be canonical relative paths.")
                target = fixture_root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(base64.b64decode(encoded, validate=True))
        outputs = prepare_data(transaction_name, data_root)
        source_signature = source_code_signature(directory)
        completed = subprocess.run(
            [str(PYTHON), "-B", str(Path(__file__).resolve()), "--transaction", transaction_name, "--worker"],
            input=json.dumps({"input": value, "expected": expected, "run_id": run_id, "data_directory": str(outputs), "test_run": test_run, "source_signature": source_signature, "input_directory": fixture_directory.name if fixture_directory else None, "index_batch": index_batch}), text=True, capture_output=True,
            cwd=str(PROJECT), timeout=timeout, check=True,
        )
        worker_stderr = completed.stderr
        packet = json.loads(completed.stdout)
        result = packet["output"] if expected is not None else packet
        validate_output(result, transaction_name, run_id)
        validate_saved_output(result, transaction_name, outputs)
        if result["input"]["raw_input"] != value["raw_input"]:
            raise ValueError("Transaction changed raw_input.")
        record.update(
            raw_input=result["input"]["raw_input"],
            transaction_input=result["input"]["processed_input"],
            output=result["output"], output_format=result["output_format"],
            status=result["status"], error=result["error"],
            meta_data=result["meta_data"],
        )
        return packet
    except subprocess.TimeoutExpired as exc:
        worker_stderr = exc.stderr
        record["error"] = {"code": "runner_timeout", "message": f"Execution exceeded {timeout:g} seconds."}
        raise
    except (subprocess.SubprocessError, ValueError, OSError, KeyError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            worker_stderr = exc.stderr
        record["error"] = {"code": "runner_error", "message": str(exc)}
        raise
    finally:
        if fixture_directory is not None:
            fixture_directory.cleanup()
        if isolated is not None:
            isolated.cleanup()
        if worker_stderr:
            if isinstance(worker_stderr, bytes):
                worker_stderr = worker_stderr.decode("utf-8", errors="replace")
            LOGGER.info("Worker diagnostics:\n%s", worker_stderr.rstrip())
        if not test_run:
            with (directory / "logs" / "run.log").open("a", encoding="utf-8") as log:
                fcntl.flock(log, fcntl.LOCK_EX)
                log.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                log.flush()
                os.fsync(log.fileno())


@log_execution
def run_tests(transaction_name, cases_path, log_path, *, timeout=20, summary=False):
    verify_environment()
    directory, entry = resolve_transaction(transaction_name)
    if log_path.resolve() != (directory / "logs" / "test-report.log").resolve():
        raise ValueError("Test results must be written to the selected transaction test-report.log.")
    logs_directory(directory)
    cases_bytes = cases_path.read_bytes()
    cases = json.loads(cases_bytes)
    source_hashes = {name.removesuffix(".py") + "_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                     for name, path in (("implementation.py", directory / "transaction.py"),
                                        ("validator.py", directory / "validator.py"),
                                        ("runner.py", Path(__file__)))}
    source_hashes["cases_sha256"] = hashlib.sha256(cases_bytes).hexdigest()
    for case in cases:
        validate_input(directory, entry, case["input"])
        if not isinstance(case["expected"], dict):
            raise ValueError("Test expectations must be JSON objects.")
    all_passed = True
    failed_case_ids = []
    for case in cases:
        value = case["input"]
        started = datetime.now(timezone.utc).isoformat()
        begin = time.monotonic()
        run_id = str(uuid.uuid4())
        actual, execution_error = None, None
        failures = []
        try:
            packet = invoke(transaction_name, value, test_run=True, expected=case["expected"], timeout=timeout, run_id=run_id, fixture_files=case.get("fixture_files", {}))
            actual = packet["output"]
            failures.extend(packet["failed_checks"])
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            execution_error = str(exc)
            if isinstance(exc, subprocess.CalledProcessError):
                execution_error += " " + (exc.stderr or "")[-4000:]
            failures.append("Runner execution failed")
        record = {
            "run_id": run_id, "case_id": case["case_id"],
            "input_hash": canonical_hash(value),
            **source_hashes,
            "fixture_files_hash": canonical_hash(case.get("fixture_files", {})),
            "python_version": sys.version,
            "platform": sys.platform,
            "started_at": started, "duration_ms": round((time.monotonic() - begin) * 1000),
            "input": value, "expected": case["expected"], "actual": actual,
            "execution_error": execution_error, "passed": not failures, "failed_checks": failures,
        }
        # Lock both duplicate-ID checking and append to keep concurrent writers safe.
        with log_path.open("a+", encoding="utf-8") as log:
            fcntl.flock(log, fcntl.LOCK_EX)
            log.seek(0)
            if any(json.loads(line)["run_id"] == record["run_id"] for line in log if line.strip()):
                raise RuntimeError("Duplicate run_id; refusing duplicate log entry")
            log.seek(0, 2)
            log.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            log.flush()
            os.fsync(log.fileno())
        all_passed = all_passed and record["passed"]
        if not record["passed"]:
            failed_case_ids.append(record["case_id"])
        if not summary:
            print(json.dumps(record, ensure_ascii=False, separators=(",", ":")), flush=True)
    if summary:
        print(json.dumps({"transaction": transaction_name, "status": "ok" if all_passed else "error",
                          "total_cases": len(cases), "passed_cases": len(cases) - len(failed_case_ids),
                          "failed_cases": len(failed_case_ids), "failed_case_ids": failed_case_ids,
                          "report": f"transactions/{transaction_name}/logs/test-report.log"},
                         ensure_ascii=False, separators=(",", ":")), flush=True)
    return all_passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transaction", required=True, help="Project transaction folder name")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--input", help="JSON object of named transaction arguments")
    mode.add_argument("--cases", type=Path)
    parser.add_argument("--summary", action="store_true", help="Emit one test summary; complete records remain in logs/test-report.log")
    parser.add_argument("--log", type=Path, help="Selected transaction test-report.log (tests only)")
    parser.add_argument("--timeout", type=float, default=20, help="Worker timeout in seconds (0 < timeout <= 300)")
    parser.add_argument("--rerun", action="store_true", help="Confirm rerunning an already executed production input")
    args = parser.parse_args()
    verify_environment()
    directory, _ = resolve_transaction(args.transaction)
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("--timeout must be greater than zero and at most 300 seconds")
    if args.summary and (not args.cases or args.worker):
        parser.error("--summary requires --cases and cannot be used by workers")
    if args.log and not args.cases:
        parser.error("--log requires --cases")
    if args.rerun and (args.worker or args.cases or args.input is None):
        parser.error("--rerun requires production --input")
    if not args.worker:
        logs_directory(directory)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr) if args.worker else
                  logging.FileHandler(directory / "logs" / "runner.log", mode="a", encoding="utf-8")],
    )
    # Repeat these checks under logging so their timing is recorded as well.
    verify_environment()
    resolve_transaction(args.transaction)
    if args.worker:
        payload = json.load(sys.stdin)
        worker(args.transaction, payload["input"], payload["expected"], payload["run_id"], payload["data_directory"], payload["test_run"], payload["source_signature"], payload.get("input_directory"), payload.get("index_batch"))
    elif args.cases:
        passed = run_tests(args.transaction, args.cases.resolve(),
                           (args.log or directory / "logs" / "test-report.log").resolve(), timeout=args.timeout, summary=args.summary)
        if not passed:
            parser.exit(1)
    elif args.input is not None:
        value = json.loads(args.input)
        try:
            result = invoke(args.transaction, value, timeout=args.timeout, rerun=args.rerun)
        except DuplicateInputError as exc:
            print(str(exc), file=sys.stderr)
            if not sys.stdin.isatty():
                parser.exit(2)
            print("Run this input again? [y/N] ", end="", file=sys.stderr, flush=True)
            try:
                answer = input().strip().lower()
            except EOFError:
                answer = ""
            if answer not in ("y", "yes"):
                print("Rerun cancelled; transaction was not executed.", file=sys.stderr)
                parser.exit(0)
            result = invoke(args.transaction, value, timeout=args.timeout, rerun=True)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        parser.error("Supply --input JSON, or --cases PATH")


if __name__ == "__main__":
    main()
