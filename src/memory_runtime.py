"""Read-only runtime and file checks for the bounded memory package."""

import hashlib
from importlib.metadata import version
import json
from pathlib import Path, PurePosixPath
import platform
import sys


ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("expected a simple relative POSIX path")
    value = PurePosixPath(relative)
    if value.is_absolute() or value.as_posix() != relative or any(part in {".", ".."} or part.startswith(".") for part in value.parts):
        raise ValueError("invalid package path")
    root = Path(root).resolve()
    target = root.joinpath(*value.parts)
    if any(root.joinpath(*value.parts[:i]).is_symlink() for i in range(1, len(value.parts) + 1)) or not target.resolve().is_relative_to(root):
        raise ValueError("package paths cannot escape or follow symlinks")
    return target


def verify_files(root, files):
    if not isinstance(files, list) or not files:
        raise ValueError("explicit file hashes are required")
    seen = set()
    for row in files:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"} or row["path"].casefold() in seen:
            raise ValueError("invalid or duplicate file entry")
        seen.add(row["path"].casefold())
        if sha(safe_path(root, row["path"])) != row["sha256"]:
            raise ValueError("file hash differs: " + row["path"])


def check_runtime(lock_path, *, require_exact_python=False):
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    if platform.system() != "Linux" or sys.version_info[:2] != (3, 12) or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("this wheel package requires Linux x86_64 CPython 3.12")
    installed = {name: version(name) for name in lock["packages"]}
    if installed != lock["packages"]:
        raise RuntimeError("installed dependencies differ from runtime-lock.json; use the staged offline wheels in a fresh environment")
    exact = platform.python_version() == lock["python"]
    if require_exact_python and not exact:
        raise RuntimeError("exact checkpoint reproduction requires CPython " + lock["python"])
    return {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(), "packages": installed, "checkpoint_python_match": exact}
