"""Use the verified installed CPython 3.12 without downloading an interpreter."""

import json
from pathlib import Path
import platform


TRUSTED_PYTHON312 = Path("/usr/bin/python3.12")
RUNTIME_PROBE = "import importlib.util,json,platform,sys; print(json.dumps({'implementation':platform.python_implementation(),'version':list(sys.version_info[:3]),'system':platform.system(),'machine':platform.machine(),'venv_available':importlib.util.find_spec('venv') is not None,'is_venv':sys.prefix!=sys.base_prefix}))"


def _verify_python312(value, *, require_venv=False):
    if not isinstance(value, dict) or value.get("implementation") != "CPython" or value.get("version", [])[:2] != [3, 12] or value.get("system") != "Linux" or value.get("machine", "").lower() not in {"x86_64", "amd64"} or value.get("venv_available") is not True:
        raise RuntimeError("installed runtime must be Linux x86_64 CPython 3.12 with venv")
    if require_venv and value.get("is_venv") is not True:
        raise RuntimeError("child interpreter must be an isolated virtual environment")


def prepare_installed_runtime(run_root, child_env, host_python, *, runner):
    run_root = Path(run_root)
    runtime = run_root / "runtime"
    if runtime.exists():
        raise FileExistsError("fresh child runtime directory is required")
    if not TRUSTED_PYTHON312.is_file():
        raise RuntimeError("verified /usr/bin/python3.12 is unavailable; no download fallback")
    options = dict(check=True, cwd=run_root, env=child_env, timeout=30, capture_output=True, text=True)
    probe = runner([str(TRUSTED_PYTHON312), "-I", "-c", RUNTIME_PROBE], **options)
    selected = json.loads(probe.stdout)
    _verify_python312(selected)
    pip_help = runner([str(host_python), "-I", "-m", "pip", "--help"], **options)
    if "--python" not in pip_help.stdout:
        raise RuntimeError("existing host pip lacks --python support; no bootstrap fallback")
    create_options = {**options, "timeout": 60}
    runner([str(TRUSTED_PYTHON312), "-I", "-m", "venv", "--without-pip", "--copies", str(runtime)], **create_options)
    child_python = runtime / "bin/python"
    if not child_python.is_file():
        raise RuntimeError("CPython 3.12 venv did not create its interpreter")
    child_probe = runner([str(child_python), "-I", "-c", RUNTIME_PROBE], **options)
    child = json.loads(child_probe.stdout)
    _verify_python312(child, require_venv=True)
    receipt = {
        "host_python_version": platform.python_version(),
        "selected_interpreter": str(TRUSTED_PYTHON312),
        "selected_runtime": selected, "child_runtime": child,
        "host_pip_python_option_verified": True,
        "pip_bootstrapped_in_child": False, "interpreter_downloaded": False,
    }
    (run_root / "bootstrap-runtime-check.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return child_python, receipt


def offline_install_command(host_python, child_python, wheel_directory, requirements):
    return [str(host_python), "-I", "-m", "pip", "--python", str(child_python), "install",
            "--no-index", "--no-deps", "--only-binary=:all:", "--require-hashes",
            "--no-cache-dir", "--disable-pip-version-check", "--find-links=" + str(wheel_directory),
            "-r", str(requirements)]
