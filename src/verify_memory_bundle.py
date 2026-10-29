"""Verify package bytes and embedded notebook sources without executing cells."""

import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path

from memory_runtime import safe_path


ROOT = Path(__file__).resolve().parent


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "bundle-manifest.json").read_text())
    expected = {row["path"]: row for row in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("duplicate bundle paths")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != set(expected) | {"bundle-manifest.json"}:
        raise ValueError("bundle inventory changed; keep outputs and virtual environments outside the package")
    for name, row in expected.items():
        path = safe_path(root, name)
        data = path.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("bundle hash differs: " + name)
    notebook_count = 0
    for path in (root / "notebooks").glob("*.ipynb"):
        nb = json.loads(path.read_text())
        if nb["nbformat"] != 4 or nb["nbformat_minor"] != 5:
            raise ValueError("unsupported notebook format")
        for cell in nb["cells"]:
            if cell["cell_type"] == "code":
                if cell["outputs"] or cell["execution_count"] is not None:
                    raise ValueError("source notebooks must be unexecuted")
                compile("".join(cell["source"]), str(path), "exec")
        setup = ast.parse("".join(nb["cells"][1]["source"]))
        assignment = next(node for node in setup.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PACKAGE" for target in node.targets))
        encoded = ast.literal_eval(assignment.value.args[0].args[0])
        payload = json.loads(base64.b64decode(encoded, validate=True))
        profile = payload["configuration"]["profile"]
        if profile not in {"two_fixture_smoke", "public_seed0_reproduction", "gateway_dryrun_or_competition_rerun"}:
            raise ValueError("unknown notebook profile")
        for name, row in payload["files"].items():
            data = base64.b64decode(row["base64"], validate=True)
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("embedded digest differs")
            mapped = name
            if profile == "two_fixture_smoke":
                if name.startswith("environment_files/"):
                    mapped = "fixture_" + name
                elif name == "assets-manifest.json":
                    mapped = "fixture-assets-manifest.json"
            if data != safe_path(root, mapped).read_bytes():
                raise ValueError("embedded source differs from package file: " + mapped)
        notebook_count += 1
    if notebook_count != 3:
        raise ValueError("expected exactly three packaged notebook profiles")
    return {"status": "passed", "files": len(expected) + 1, "notebooks": notebook_count, "competition_submission": False, "hosted_kaggle_validation": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(verify(args.package)))


if __name__ == "__main__":
    main()
