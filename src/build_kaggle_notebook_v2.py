"""Add the documented Kaggle phase handoff without changing packaged sources."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def build(source):
    source = Path(source)
    original_bytes = source.read_bytes()
    notebook = json.loads(original_bytes)
    helper_bytes = (ROOT / "kaggle_phase_gate_v2.py").read_bytes()
    helper = helper_bytes.decode("utf-8")
    execution = notebook["cells"][-1]
    body = execution["source"]
    body = "".join(body) if isinstance(body, list) else body
    anchor = 'subprocess.run(command, check=True, cwd=RUN_ROOT, env=CHILD_ENV, timeout=30000, capture_output=True, text=True)'
    assert body.count(anchor) == 1
    execution["source"] = body.replace(anchor, "wait_for_gateway(rerun)\n" + anchor).replace("subprocess.run(", "run_checked(")
    diagnostic_anchor = 'checked = run_checked([str(CHILD_PY), "-B", "-c", validate_code, str(RUN_ROOT / "gateway-results")], check=True, cwd=RUN_ROOT, env=CHILD_ENV, timeout=30, capture_output=True, text=True)'
    assert execution["source"].count(diagnostic_anchor) == 1
    execution["source"] = execution["source"].replace(
        diagnostic_anchor,
        'diagnostic = run_postclose_diagnostic(report, [str(CHILD_PY), "-B", "-c", validate_code, str(RUN_ROOT / "gateway-results")], cwd=RUN_ROOT, env=CHILD_ENV, timeout=30, capture_output=True, text=True)',
    ).replace(
        '(RUN_ROOT / "gateway-artifact-validation.json").write_text(checked.stdout, encoding="utf-8")',
        '(RUN_ROOT / "gateway-artifact-validation.json").write_text(json.dumps(diagnostic, indent=2) + "\\n", encoding="utf-8")\n    print(json.dumps({"postclosure_local_diagnostic": diagnostic["status"], "exit_code": diagnostic["exit_code"]}))',
    )
    dependencies = notebook["cells"][2]
    dependency_body = dependencies["source"]
    dependency_body = "".join(dependency_body) if isinstance(dependency_body, list) else dependency_body
    dependencies["source"] = dependency_body.replace("subprocess.run(", "run_checked(")
    notebook["cells"].insert(2, {
        "cell_type": "code", "id": "kaggle-phase-gate", "metadata": {}, "outputs": [],
        "execution_count": None, "source": helper,
    })
    notebook["cells"].append({
        "cell_type": "code", "id": "commit-placeholder", "metadata": {}, "outputs": [], "execution_count": None,
        "source": 'if not rerun:\n    commit_file = write_commit_placeholder(False)\n    print("Commit-stage placeholder for Kaggle selection only:", commit_file)\n    print("No measured score is encoded. The competition gateway must create the real output during rerun.")\n',
    })
    intro = notebook["cells"][0]["source"]
    intro = "".join(intro) if isinstance(intro, list) else intro
    notebook["cells"][0]["source"] = intro.replace(
        "This notebook creates no submission placeholder.",
        "Outside a competition rerun, this notebook writes a labeled commit-stage placeholder so Kaggle can select the notebook for evaluation. The competition gateway must generate the real submission during rerun; this notebook never writes a fallback in that branch.",
    )
    notebook["metadata"]["kaggle_phase_handoff"] = {
        "source_notebook_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "helper_sha256": hashlib.sha256(helper_bytes).hexdigest(),
        "embedded_runtime_sources_unchanged": True,
        "gateway_readiness_timeout_seconds": 600,
        "bounded_child_error_log_characters_per_stream": 16384,
        "nonfatal_diagnostics_require_protocol_completed_and_scorecard_closed": True,
        "commit_placeholder_is_scored_result": False,
        "hosted_validation": False,
    }
    return notebook


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "arc-memory-kaggle-v2.ipynb")
    arguments = parser.parse_args()
    result = build(arguments.source)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(arguments.output)
