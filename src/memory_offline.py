"""Replay the fixed memory policy with the frozen matched observation runner."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from unittest.mock import patch

from memory_runtime import check_runtime, sha, verify_files


ROOT = Path(__file__).resolve().parent


def run_memory_offline(*, assets, manifest_path, output, runtime_lock, source_lock,
                       games=None, max_actions=500, max_seconds=10):
    if type(max_actions) is not int or not 0 <= max_actions <= 500:
        raise ValueError("max_actions must be an integer from zero to 500")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 10:
        raise ValueError("max_seconds must be finite and at most 10")
    assets, manifest_path, output = Path(assets).resolve(), Path(manifest_path), Path(output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["asset_kind"] not in {"public_game_local_only", "toolkit_test_fixture"}:
        raise ValueError("unsupported evidence kind")
    verify_files(assets, manifest["files"])
    expected_inventory = {row["path"] for row in manifest["files"]}
    actual_inventory = {path.relative_to(assets).as_posix() for path in assets.rglob("*") if path.is_file()}
    if actual_inventory != expected_inventory:
        raise ValueError("asset inventory differs from the explicit manifest")
    sources = json.loads(Path(source_lock).read_text(encoding="utf-8"))
    verify_files(ROOT, sources["files"])
    runtime = check_runtime(runtime_lock, require_exact_python=True)
    known = {row["id"]: row for row in manifest["games"]}
    games = list(known) if games is None else list(games)
    if not games or len(games) != len(set(games)) or not set(games).issubset(known):
        raise ValueError("games must be unique manifest identifiers")
    expected_ids = {name: json.loads((assets / known[name]["metadata"]).read_text(encoding="utf-8"))["game_id"] for name in games}
    reference = None
    if manifest["asset_kind"] == "public_game_local_only":
        if max_actions != 500 or max_seconds != 10:
            raise ValueError("public checkpoint replay requires the unchanged 500-action/10-second budgets")
        reference = json.loads((ROOT / "checkpoint-reference.json").read_text(encoding="utf-8"))
        if reference["asset_files_sha256"] != {row["path"]: row["sha256"] for row in manifest["files"]}:
            raise ValueError("public assets differ from the preserved checkpoint")
        for name, expected in reference["sources_sha256"].items():
            if sha(ROOT / name) != expected:
                raise ValueError("execution source differs from the preserved checkpoint")
    output.mkdir(parents=True, exist_ok=False)
    # Import after pins and file verification. No game module is loaded here.
    from run_matched_v2 import evaluate
    from run_offline import offline_guard
    from validate_memory_artifacts import validate_closed_scorecard
    args = argparse.Namespace(output=output, assets=assets, max_actions=max_actions,
                              max_seconds=max_seconds, expected_game_ids=expected_ids,
                              initial_observations={})
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "running",
        "evidence_type": manifest["asset_kind"], "policy": "transition_memory", "seed": 0,
        "competition_submission": False, "hosted_kaggle_validation": False,
        "runtime": runtime, "asset_manifest_sha256": sha(manifest_path),
        "source_lock_sha256": sha(source_lock), "max_actions": max_actions,
        "checkpoint_reference_sha256": sha(ROOT / "checkpoint-reference.json") if reference else None,
        "max_seconds_cooperative": max_seconds, "runs": [], "artifact_checks": [],
        "checkpoint_limit": "one seed on familiar public games; zero full wins in the preserved checkpoint; planning had no added score benefit",
    }
    try:
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}), offline_guard():
            for game in games:
                result = evaluate(game, 0, "transition_memory", args)
                # The frozen evaluator's original public-data label is metadata,
                # not an inference about this adapter's supplied asset set.
                result["evidence_type"] = manifest["asset_kind"]
                summary_path = output / f"{game}-transition_memory-seed0/summary.json"
                if summary_path.exists():
                    summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                report["runs"].append(result)
                if result["status"] != "passed":
                    raise RuntimeError("memory case failed; stop before further cases")
                if reference is not None:
                    expected = reference["games"][game]
                    if (result["game_id"] != expected["game_id"] or
                            result["baseline_compatible_transcript_sha256"] != expected["baseline_compatible_transcript_sha256"] or
                            not math.isclose(result["local_toolkit_score_percent"], expected["local_toolkit_score_percent"], rel_tol=0, abs_tol=1e-12)):
                        raise RuntimeError("public checkpoint replay differs; stop before further cases")
                card = json.loads((output / f"{game}-transition_memory-seed0/local-scorecard.json").read_text())
                case_dir = summary_path.parent
                actions = [json.loads(line) for line in (case_dir / "actions.jsonl").read_text().splitlines()]
                attempts = [json.loads(line) for line in (case_dir / "attempts.jsonl").read_text().splitlines()]
                if (result["scorecard_cleanup"]["status"] != "closed" or
                        len(actions) != len(attempts) or len(actions) != result["actions"] or
                        hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest() != result["action_transcript_sha256"]):
                    raise RuntimeError("offline producer evidence does not reconcile")
                checked = validate_closed_scorecard(card, [result], [expected_ids[game]], competition_mode=None)
                checked["artifacts_sha256"] = {name: sha(case_dir / name) for name in ["actions.jsonl", "attempts.jsonl", "local-scorecard.json", "summary.json"]}
                checked["producer_source_lock_sha256"] = report["source_lock_sha256"]
                report["artifact_checks"].append(checked)
        verify_files(ROOT, sources["files"])
        verify_files(assets, manifest["files"])
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        (output / "memory-offline-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, default=ROOT / "runtime-lock.json")
    parser.add_argument("--source-lock", type=Path, default=ROOT / "source-lock.json")
    parser.add_argument("--games", nargs="+")
    parser.add_argument("--max-actions", type=int, default=500)
    parser.add_argument("--max-seconds", type=float, default=10)
    args = parser.parse_args()
    report = run_memory_offline(assets=args.assets, manifest_path=args.manifest, output=args.output,
                               runtime_lock=args.runtime_lock, source_lock=args.source_lock,
                               games=args.games, max_actions=args.max_actions, max_seconds=args.max_seconds)
    print(json.dumps({"status": report["status"], "cases": len(report["runs"]), "competition_submission": False}))


if __name__ == "__main__":
    main()
