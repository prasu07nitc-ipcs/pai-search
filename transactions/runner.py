"""Transaction runner with exclusive data ownership (macOS, Python 3.11+).

STRICT dependency policy: runner infrastructure must use only Python built-ins
and the standard library. No third-party, optional, vendored, or indirect Python
dependencies. See transactions/AGENTS.md for the authoritative policy.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import inspect
import math
import re
import types
import typing
import ctypes
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
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
SOURCE_FILE_FIELDS = {
    "tx-save-article": ("meta_data_file_path", "article_file_path"),
    "tx-bookmark": ("meta_data_file_path",),
    "tx-index": ("context_file_path", "meta_data_file_path"),
}


def canonical_hash(value):
    """Stable JSON identity; preserve the production run-ID byte contract."""
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def owned_data_name(transaction_name):
    """Runner-owned mapping; transaction definitions cannot choose destinations."""
    if transaction_name == "tx-articles":
        raise ValueError("data/articles/ is exclusively reserved for tx-save-article.")
    return "articles" if transaction_name == "tx-save-article" else transaction_name[3:]


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
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if any((ancestor / ".git").exists() for ancestor in (directory, *directory.parents)):
            raise ValueError("Cannot capture source signature inside a Git repository.") from exc
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
    for name in ("run.log", "runner.log"):
        path = target / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
            raise ValueError("Logs must be regular, unlinked files")
    return target


class DuplicateInputError(ValueError):
    """A previous production execution requires explicit rerun confirmation."""


@contextlib.contextmanager
def production_history(directory):
    """Read available history without locking or creating a result log."""
    try:
        history = (directory / "logs" / "run.log").open("r", encoding="utf-8")
    except FileNotFoundError:
        yield ()
        return
    with history:
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
            if directory.name not in ("tx-bookmark", "tx-save-article", "tx-index") or record["raw_input"] is not None:
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
        LOGGER.debug("Function %s started", function.__qualname__)
        try:
            result = function(*args, **kwargs)
        except BaseException:
            LOGGER.exception(
                "Function %s failed; total execution time: %.6f seconds",
                function.__qualname__, time.perf_counter() - started,
            )
            raise
        (LOGGER.info if function.__name__ == "_invoke" else LOGGER.debug)(
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
    for filename in ("TRANSACTION.md", "AGENTS.md", "transaction.py"):
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
    return directory, entry[1]


@log_execution
def validate_input(directory, entry, value):
    """Bind JSON arguments against the source signature without importing transaction code."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Input must be a JSON object of named arguments.")
    if directory.name not in ("tx-bookmark", "tx-save-article", "tx-index") and not isinstance(value.get("raw_input"), str):
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
    arguments_value = value
    inspect.Signature(parameters).bind(**arguments_value)
    # Validate primitive/nullable annotations before creating storage or a worker.
    primitives = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
    def annotation_type(node):
        if isinstance(node, ast.Name) and node.id in primitives:
            return primitives[node.id]
        if isinstance(node, ast.Constant) and node.value is None:
            return type(None)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            left, right = annotation_type(node.left), annotation_type(node.right)
            if left is not None and right is not None:
                return typing.Union[left, right]
        return None

    for argument in positional + arguments.kwonlyargs:
        if argument.annotation is None:
            raise ValueError(f"Parameter {argument.arg} must have an explicit type annotation.")
        annotation = annotation_type(argument.annotation)
        if argument.arg in arguments_value and annotation is not None:
            if not matches_type(arguments_value[argument.arg], annotation):
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
            or not (inputs["raw_input"] is None if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") else isinstance(inputs["raw_input"], str))
            or not isinstance(inputs["processed_input"], dict)):
        raise ValueError("input requires processed_input object and raw_input (null for tx-bookmark, tx-save-article and tx-index, otherwise a string).")
    if not isinstance(result["meta_data"], dict):
        raise ValueError("meta_data must be an object.")
    if not isinstance(result.get("output_format"), str) or not result["output_format"].strip():
        raise ValueError("output_format must be a non-empty string.")
    if transaction_name in SOURCE_FILE_FIELDS and result["output_format"] != "markdown":
        raise ValueError("Transaction output_format must be markdown.")
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
                try:
                    info = item.lstat()
                except FileNotFoundError:
                    # Concurrent atomic replacement can remove a scanned temp name.
                    # Live output targets still receive their own validation below.
                    continue
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
    if target.is_symlink() or target.resolve() != target:
        raise ValueError("Owned data directory must be canonical and not a symlink.")
    target.mkdir(exist_ok=True)
    # The worker performs the full-tree check before sandboxing/import. Avoid
    # scanning unrelated page files again in the parent and after every result.
    return target


def validate_saved_output(result, transaction_name, destination):
    if result["status"] != "ok":
        return
    # Verify only returned paths; the worker scans the owned tree before import.
    for output in result["output"]:
        relative = Path(output).relative_to(Path("data") / owned_data_name(transaction_name))
        descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in relative.parts[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=descriptor)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Successful output must identify regular unlinked owned files.")
            finally:
                os.close(fd)
        finally:
            os.close(descriptor)


@log_execution
def worker(transaction_name, value, run_id=None, data_directory=None, source_signature=None):
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
    if outputs != DATA / owned_data_name(transaction_name):
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
             '(deny file-link)', '(deny network*)']
    for path in readable:
        rules.append('(allow file-read* (subpath ' + json.dumps(str(path)) + '))')
    # Grant only the selected source files, never their producer directories.
    for field in SOURCE_FILE_FIELDS.get(transaction_name, ()):
        source = Path(value[field])
        if not source.is_absolute():
            source = PROJECT / source
        rules.append('(allow file-read* (literal ' + json.dumps(str(source.resolve())) + '))')
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
    if not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{64}", run_id) is None:
        raise ValueError("Invalid execution run_id.")
    os.environ["PROJECT_TRANSACTION_SOURCE_SIGNATURE"] = json.dumps(source_signature)
    os.environ["PROJECT_TRANSACTION_SIGNATURE_MARKDOWN"] = signature_markdown(source_signature)
    os.environ["PROJECT_TRANSACTION_RUN_ID"] = run_id
    os.environ["PROJECT_TRANSACTION_DATA_DIRECTORY"] = str(outputs)
    if transaction_name in ("tx-save-article", "tx-bookmark", "tx-index"):
        os.environ["PROJECT_TRANSACTION_INPUT_ROOT"] = str(PROJECT)
    if transaction_name == "tx-index":
        os.environ["PROJECT_TRANSACTION_TIMEZONE"] = "Asia/Kolkata"
    # Keep transaction prints away from the JSON transport on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        module = load_module(directory / "transaction.py", "project_" + transaction_name.replace("-", "_"))
        function = getattr(module, entry)
        signature = inspect.signature(function)
        call_value = value
        bound = signature.bind(**call_value)
        bound.apply_defaults()
        hints = typing.get_type_hints(function)
        for name, argument in bound.arguments.items():
            if name not in hints or not matches_type(argument, hints[name]):
                raise ValueError(f"Incorrect type for argument {name}.")
        result = log_execution(function)(**call_value)
        validate_output(result, transaction_name, run_id)
        validate_saved_output(result, transaction_name, outputs)
        if result["input"]["raw_input"] != (None if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") else value["raw_input"]):
            raise ValueError("Transaction changed raw_input.")
        if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") and result["input"]["processed_input"] != value:
            raise ValueError("Transaction changed supplied input.")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def invoke(transaction_name, value, **options):
    return _invoke(transaction_name, value, **options)


@log_execution
def _invoke(transaction_name, value, *, timeout=20, rerun=False):
    verify_environment()
    directory, entry = resolve_transaction(transaction_name)
    validate_input(directory, entry, value)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("Timeout must be greater than zero and at most 300 seconds.")
    logs_directory(directory)
    input_id = canonical_hash(value)
    if not rerun and transaction_name != "tx-index":
        log_execution(require_new_input)(directory, input_id)
    run_id = input_id
    record = {
        "run_id": run_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "processed_input": dict(value) if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") else {key: argument for key, argument in value.items() if key != "raw_input"},
        "raw_input": None if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") else value["raw_input"], "transaction_input": None,
        "output": None, "output_format": None,
        "status": "error", "error": None, "meta_data": None,
    }
    worker_stderr = None
    try:
        outputs = prepare_data(transaction_name, DATA)
        source_signature = source_code_signature(directory)
        completed = subprocess.run(
            [str(PYTHON), "-B", str(Path(__file__).resolve()), "--transaction", transaction_name, "--worker"]
            + (["--verbose"] if LOGGER.isEnabledFor(logging.DEBUG) else []),
            input=json.dumps({"input": value, "run_id": run_id, "data_directory": str(outputs), "source_signature": source_signature}, ensure_ascii=False, allow_nan=False, separators=(",", ":")), text=True, encoding="utf-8", capture_output=True,
            cwd=str(PROJECT), timeout=timeout, check=True,
        )
        worker_stderr = completed.stderr
        packet = json.loads(completed.stdout)
        result = packet
        validate_output(result, transaction_name, run_id)
        validate_saved_output(result, transaction_name, outputs)
        if result["input"]["raw_input"] != (None if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") else value["raw_input"]):
            raise ValueError("Transaction changed raw_input.")
        if transaction_name in ("tx-bookmark", "tx-save-article", "tx-index") and result["input"]["processed_input"] != value:
            raise ValueError("Transaction changed supplied input.")
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
        if worker_stderr:
            if isinstance(worker_stderr, bytes):
                worker_stderr = worker_stderr.decode("utf-8", errors="replace")
            LOGGER.info("Worker diagnostics:\n%s", worker_stderr.rstrip())
        append_production_record(directory, record)


def append_production_record(directory, record):
    """Append one complete UTF-8 JSON line in one O_APPEND write, without locks."""
    payload = (json.dumps(record, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(directory / "logs" / "run.log",
                         os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Production log must be a regular unlinked file.")
        if os.write(descriptor, payload) != len(payload):
            raise OSError("Incomplete production log append.")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transaction", required=True, help="Project transaction folder name")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--input", help="JSON object of named arguments; use - to read UTF-8 JSON from stdin")
    parser.add_argument("--verbose", action="store_true", help="Record per-function diagnostic timings")
    parser.add_argument("--timeout", type=float, default=20, help="Worker timeout in seconds (0 < timeout <= 300)")
    parser.add_argument("--rerun", action="store_true", help="Confirm rerunning an already executed production input")
    args = parser.parse_args()
    verify_environment()
    directory, _ = resolve_transaction(args.transaction)
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("--timeout must be greater than zero and at most 300 seconds")
    if args.rerun and (args.worker or args.input is None):
        parser.error("--rerun requires production --input")
    if not args.worker:
        logs_directory(directory)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr) if args.worker else
                  logging.FileHandler(directory / "logs" / "runner.log", mode="a", encoding="utf-8")],
    )
    if args.worker:
        payload = json.load(sys.stdin)
        worker(args.transaction, payload["input"], payload["run_id"], payload["data_directory"], payload["source_signature"])
    elif args.input is not None:
        value = json.load(sys.stdin) if args.input == "-" else json.loads(args.input)
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
        parser.error("Supply --input JSON")


if __name__ == "__main__":
    main()
