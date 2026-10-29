"""Adapt the immutable v2 wrapper to the verified installed Python 3.12."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
V2_SHA256 = "10a62ffe01f62fd1f4db47ac9fe3b0ce384767fbcaeb7b09736016e1a17fee11"


def build():
    source = (ROOT / "arc-memory-kaggle-v2.ipynb").read_bytes()
    if hashlib.sha256(source).hexdigest() != V2_SHA256:
        raise ValueError("approved v2 notebook changed")
    notebook = json.loads(source)
    bootstrap = notebook["cells"][1]["source"]
    bootstrap = "".join(bootstrap) if isinstance(bootstrap, list) else bootstrap
    guard = 'if platform.system() != "Linux" or sys.version_info[:2] != (3, 12) or platform.machine().lower() not in {"x86_64", "amd64"}:'
    assert bootstrap.count(guard) == 1
    notebook["cells"][1]["source"] = bootstrap.replace(guard, 'if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:').replace(
        'Staged wheels require Linux x86_64 CPython 3.12; no external installation fallback',
        'Bootstrap requires Linux x86_64; staged wheels execute only in verified installed CPython 3.12',
    )
    runtime_helper = (ROOT / "bootstrap_runtime_v3.py").read_text(encoding="utf-8")
    notebook["cells"][2]["source"] += "\n\n" + runtime_helper
    dependencies = notebook["cells"][3]["source"]
    old = 'venv.EnvBuilder(with_pip=True, symlinks=False).create(RUN_ROOT / "runtime")\nCHILD_PY = RUN_ROOT / "runtime/bin/python"'
    assert dependencies.count(old) == 1
    dependencies = dependencies.replace("import venv\n", "").replace(old, 'CHILD_PY, bootstrap_check = prepare_installed_runtime(RUN_ROOT, CHILD_ENV, sys.executable, runner=run_checked)\nprint(json.dumps(bootstrap_check, indent=2))')
    old_install = 'install = [str(CHILD_PY), "-m", "pip", "install", "--no-index", "--no-deps", "--only-binary=:all:", "--require-hashes", "--no-cache-dir", "--disable-pip-version-check", "--find-links=" + str(WHEEL_DIR), "-r", str(RUN_ROOT / "requirements-linux.txt")]'
    assert dependencies.count(old_install) == 1
    notebook["cells"][3]["source"] = dependencies.replace(old_install, 'install = offline_install_command(sys.executable, CHILD_PY, WHEEL_DIR, RUN_ROOT / "requirements-linux.txt")')
    intro = notebook["cells"][0]["source"]
    intro = "".join(intro) if isinstance(intro, list) else intro
    notebook["cells"][0]["source"] = intro + "\n\nThe notebook host may use Python 3.13. The locked agent runtime still requires installed `/usr/bin/python3.12`, which is probed before creating a pipless child environment. Existing host pip installs only the staged, hash-locked wheels through its documented `--python` option. No interpreter or package-index fallback exists.\n"
    notebook["metadata"]["installed_runtime_bootstrap_v3"] = {
        "source_v2_sha256": V2_SHA256,
        "helper_sha256": hashlib.sha256(runtime_helper.encode()).hexdigest(),
        "trusted_interpreter": "/usr/bin/python3.12",
        "agent_abi": "Linux x86_64 CPython 3.12",
        "venv_pip_bootstrap": False, "interpreter_download": False,
        "embedded_runtime_sources_and_locks_unchanged": True,
        "hosted_validation": False,
    }
    return notebook


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "arc-memory-kaggle-v3.ipynb")
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(build(), stream, indent=2)
        stream.write("\n")
    print(args.output)
