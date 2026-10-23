"""Shared production tool runner (macOS, Python 3.11+)."""
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
import fcntl
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import wraps

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".venv"
PYTHON = ENV / "bin/python"
LOGGER = logging.getLogger(__name__)


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
def resolve_tool(name):
    if not isinstance(name, str) or len(name) >= 64 or not re.fullmatch(r"tool-[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Select a tool using its tool-<name> folder name.")
    directory = ROOT / name
    if directory.is_symlink() or directory.resolve().parent != ROOT:
        raise ValueError("Tool must be a direct, non-symlink project directory.")
    for filename in ("TOOL.md", "AGENTS.md", "tool.py"):
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular tool file: {filename}")
    discovery = (directory / "TOOL.md").read_text(encoding="utf-8")
    if discovery.lstrip().startswith("---"):
        raise ValueError("TOOL.md must not contain YAML frontmatter.")
    if not re.search(rf"^Name: {re.escape(name)}\s*$", discovery, re.M):
        raise ValueError("TOOL.md Name must match the tool directory.")
    if not re.search(r"^Description: \S.+$", discovery, re.M):
        raise ValueError("TOOL.md must declare a Description.")
    if not re.search(r"^Instructions: \[AGENTS\.md\]\(AGENTS\.md\)\s*$", discovery, re.M):
        raise ValueError("TOOL.md must link to AGENTS.md.")
    entry = re.search(r"^Entry point: `tool\.py:([A-Za-z_]\w*)", discovery, re.M)
    if entry is None or entry[1].startswith("_"):
        raise ValueError("TOOL.md must declare a public tool.py function entry point.")
    return directory, entry[1]


@log_execution
def validate_input(directory, entry, value):
    """Bind JSON arguments against the source signature without importing tool code."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Input must be a JSON object of named arguments.")
    json.dumps(value, allow_nan=False)
    tree = ast.parse((directory / "tool.py").read_text(encoding="utf-8"))
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == entry), None)
    if function is None:
        raise ValueError("Entry point must be a top-level synchronous function.")
    arguments = function.args
    if arguments.posonlyargs or arguments.vararg or arguments.kwarg:
        raise ValueError("Tool entry points must declare explicit named parameters.")
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
        raise ValueError("Tool entry points must declare their return type.")


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
    raise ValueError(f"Unsupported tool input annotation: {annotation!r}")


@log_execution
def validate_output(result, tool_name=None, run_id=None):
    if not isinstance(result, dict) or result.get("status") not in ("ok", "error") or "error" not in result:
        raise ValueError("Tool output must be an object with status ('ok'/'error') and error.")
    if set(result) != {"input", "output", "output_format", "status", "error", "meta_data"}:
        raise ValueError("Tool result requires exactly input, output, output_format, status, error, and meta_data.")
    inputs = result["input"]
    identity = next((key for key in ("input_text", "page_id", "raw_input") if isinstance(inputs, dict) and key in inputs), "raw_input")
    if (not isinstance(inputs, dict) or set(inputs) != {identity, "processed_input"}
            or not isinstance(inputs[identity], str) or not isinstance(inputs["processed_input"], dict)):
        raise ValueError("input requires an input_text, page_id, or legacy raw_input string and processed_input object.")
    if not isinstance(result["meta_data"], dict):
        raise ValueError("meta_data must be an object.")
    if not isinstance(result.get("output_format"), str) or not result["output_format"].strip():
        raise ValueError("output_format must be a non-empty string.")
    output = result["output"]
    if result["status"] == "ok":
        if (not isinstance(output, str) or re.fullmatch(
                r"tool-[a-z0-9]+(?:-[a-z0-9]+)*/output/(?:[0-9a-f]{64})\.(?:json|md)", output) is None
                or "/../" in output or "/./" in output):
            raise ValueError("Successful output must reference tool output/<page_id>.json or <page_id>.md relative to tools/.")
        page_id = inputs.get("page_id", result["meta_data"].get("page_id"))
        if not isinstance(page_id, str) or re.fullmatch(r"[0-9a-f]{64}", page_id) is None:
            raise ValueError("Successful output requires a valid page_id in input or meta_data.")
        if run_id is not None and page_id != run_id:
            raise ValueError("Result page_id must match execution run_id.")
        extension = {"json": "json", "markdown": "md"}.get(result["output_format"])
        if extension is None or (tool_name is not None and output != f"{tool_name}/output/{page_id}.{extension}"):
            raise ValueError("Output path must match the selected tool, page_id, and output_format.")
    elif output is not None:
        raise ValueError("Failed tool output must be null.")
    error = result["error"]
    if result["status"] == "ok":
        if error is not None:
            raise ValueError("Successful tool output must have error=null.")
    elif (not isinstance(error, dict) or set(error) != {"code", "message"}
          or any(not isinstance(error[key], str) or not error[key] for key in ("code", "message"))):
        raise ValueError("Failed tool output requires non-empty error.code and error.message strings.")
    json.dumps(result, allow_nan=False)


@log_execution
def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@log_execution
def output_directory(directory):
    """Resolve the optional tool-local write capability declared in discovery."""
    discovery = (directory / "TOOL.md").read_text(encoding="utf-8")
    if not re.search(r"^Output directory: output\s*$", discovery, re.M):
        return None
    target = directory / "output"
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("output must be a real tool-local directory.")
    if target.exists():
        for base, directories, files in os.walk(target, followlinks=False):
            for name in directories + files:
                item = Path(base) / name
                if item.is_symlink() or (item.is_file() and item.stat().st_nlink != 1):
                    raise ValueError("Output symlinks and hard-linked files are forbidden.")
    return target


@log_execution
def worker(tool_name, value, run_id=None):
    verify_environment()
    directory, entry = resolve_tool(tool_name)
    validate_input(directory, entry, value)
    if sys.platform != "darwin":
        raise RuntimeError("This runner requires macOS sandbox_init; refusing unsandboxed execution.")
    outputs = output_directory(directory)
    if outputs is not None and not outputs.is_dir():
        raise RuntimeError("Parent runner must prepare the output directory.")
    # Install a kernel-enforced sandbox before importing tool code.
    library = ctypes.CDLL("/usr/lib/libsandbox.dylib", use_errno=True)
    library.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    library.sandbox_init.restype = ctypes.c_int
    error = ctypes.c_char_p()
    readable = [directory, ENV.resolve(), Path(sys.base_prefix).resolve(),
                Path('/System'), Path('/usr/lib'), Path('/usr/share'),
                Path('/private/etc'), Path('/private/var/run'), Path('/dev'),
                Path('/Library/Apple'), Path('/Library/Preferences/SystemConfiguration')]
    rules = ['(version 1)', '(allow default)', '(deny file-read*)', '(allow file-read-metadata)',
             '(deny file-write*)', '(deny process-fork)', '(deny process-exec)',
             '(deny file-link)']
    for path in readable:
        rules.append('(allow file-read* (subpath ' + json.dumps(str(path)) + '))')
    rules.append('(allow file-read* (literal ' + json.dumps(str(Path(__file__).resolve())) + '))')
    if outputs is not None:
        rules.append('(allow file-write* (subpath ' + json.dumps(str(outputs)) + '))')
        rules.append('(deny file-write-unlink (literal ' + json.dumps(str(outputs)) + '))')
    profile = ''.join(rules).encode('utf-8')
    if library.sandbox_init(profile, 0, ctypes.byref(error)) != 0:
        raise RuntimeError("Cannot apply tool sandbox: " + (error.value or b"unknown").decode())
    # Verify the relevant restrictions rather than relying only on profile text.
    for target in (ENV / ".runner-write-probe", ROOT / "requirements.txt", ROOT / "uv.lock"):
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
    if run_id is not None:
        if not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{64}", run_id) is None:
            raise ValueError("Invalid execution run_id.")
        os.environ["PROJECT_TOOL_RUN_ID"] = run_id
    else:
        os.environ.pop("PROJECT_TOOL_RUN_ID", None)
    # Keep tool prints away from the JSON transport on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        module = load_module(directory / "tool.py", "project_" + tool_name.replace("-", "_"))
        function = getattr(module, entry)
        signature = inspect.signature(function)
        bound = signature.bind(**value)
        bound.apply_defaults()
        hints = typing.get_type_hints(function)
        for name, argument in bound.arguments.items():
            if name not in hints or not matches_type(argument, hints[name]):
                raise ValueError(f"Incorrect type for argument {name}.")
        result = log_execution(function)(**value)
        validate_output(result, tool_name, run_id)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


@log_execution
def invoke(tool_name, value, *, timeout=20):
    verify_environment()
    directory, entry = resolve_tool(tool_name)
    validate_input(directory, entry, value)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("Timeout must be greater than zero and at most 300 seconds.")
    logs_directory(directory)
    run_id = value.get("page_id")
    if run_id is not None and (not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{64}", run_id) is None):
        run_id = None
    outputs = output_directory(directory)
    if outputs is not None:
        outputs.mkdir(exist_ok=True)
        output_directory(directory)
    identity = next(key for key in ("input_text", "raw_input", "page_id") if key in value)
    record = {
        "run_id": run_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "processed_input": {key: argument for key, argument in value.items() if key != identity},
        identity: value[identity], "tool_input": None,
        "output": None, "output_format": None,
        "status": "error", "error": None, "meta_data": None,
    }
    worker_stderr = None
    try:
        completed = subprocess.run(
            [str(PYTHON), "-B", str(Path(__file__).resolve()), "--tool", tool_name, "--worker"],
            input=json.dumps({"input": value, "run_id": run_id}), text=True, capture_output=True,
            cwd=str(ROOT), timeout=timeout, check=True,
        )
        worker_stderr = completed.stderr
        result = json.loads(completed.stdout)
        validate_output(result, tool_name, run_id)
        if set(result["input"]) != {identity, "processed_input"} or result["input"][identity] != value[identity]:
            raise ValueError("Tool must preserve the supplied input identity.")
        record.update(
            run_id=run_id or (result["meta_data"].get("page_id") if result["status"] == "ok" else None),
            tool_input=result["input"]["processed_input"],
            output=result["output"], output_format=result["output_format"],
            status=result["status"], error=result["error"],
            meta_data=result["meta_data"],
        )
        return result
    except subprocess.TimeoutExpired as exc:
        worker_stderr = exc.stderr
        record["error"] = {"code": "runner_timeout", "message": f"Execution exceeded {timeout:g} seconds."}
        raise
    except (subprocess.SubprocessError, ValueError, OSError, KeyError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            worker_stderr = exc.stderr
        record.update(tool_input=None, output=None, output_format=None,
                      status="error", meta_data=None,
                      error={"code": "runner_error", "message": str(exc)})
        raise
    finally:
        if worker_stderr:
            if isinstance(worker_stderr, bytes):
                worker_stderr = worker_stderr.decode("utf-8", errors="replace")
            LOGGER.info("Worker diagnostics:\n%s", worker_stderr.rstrip())
        with (directory / "logs" / "run.log").open("a", encoding="utf-8") as log:
            fcntl.flock(log, fcntl.LOCK_EX)
            log.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            log.flush()
            os.fsync(log.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, help="Project tool folder name")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--input", help="JSON object of named tool arguments")
    parser.add_argument("--timeout", type=float, default=20, help="Worker timeout in seconds (0 < timeout <= 300)")
    args = parser.parse_args()
    verify_environment()
    directory, _ = resolve_tool(args.tool)
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("--timeout must be greater than zero and at most 300 seconds")
    if not args.worker:
        logs_directory(directory)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr) if args.worker else
                  logging.FileHandler(directory / "logs" / "runner.log", mode="a", encoding="utf-8")],
    )
    if args.worker:
        payload = json.load(sys.stdin)
        worker(args.tool, payload["input"], payload["run_id"])
    elif args.input is not None:
        value = json.loads(args.input)
        result = invoke(args.tool, value, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        parser.error("Supply --input JSON")


if __name__ == "__main__":
    main()
