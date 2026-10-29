"""Run local environments with network calls denied and truthful provenance.

Default assets are MIT toolkit test fixtures, not benchmark evaluation games.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import socket
import sys
import time
from unittest.mock import patch

from policy import BoundedExplorer, frame_fingerprint


ROOT = Path(__file__).resolve().parent


@contextmanager
def offline_guard():
    """Block process-local network and ignore inherited ARC mode/credentials."""
    def reject(*args, **kwargs):
        raise RuntimeError("network access is disabled for this offline run")

    with patch.dict(os.environ, {"OPERATION_MODE": "offline", "ARC_API_KEY": ""}):
        with patch.object(socket.socket, "connect", reject), patch.object(socket.socket, "connect_ex", reject), patch.object(socket, "create_connection", reject), patch.object(socket, "getaddrinfo", reject):
            yield


def source_manifest(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".json"} and "__pycache__" not in path.parts
    }


def run(args):
    # Import under the guard, so dependency imports cannot open the network.
    from arc_agi import Arcade, OperationMode

    assets = args.environments.resolve()
    if not assets.is_dir():
        raise ValueError(f"local environment directory missing: {assets}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for game_id in args.games:
        for seed in args.seeds:
            # A new Arcade per run keeps per-run scorecards and environment state separate.
            run_name = f"{game_id}-{args.mode}-seed{seed}"
            run_dir = output / run_name
            run_dir.mkdir(exist_ok=False)
            # Public environments may use module-level Python/NumPy RNGs as
            # well as the engine's own seeded generator.
            random.seed(seed)
            import numpy as np
            np.random.seed(seed)
            arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(assets), recordings_dir=str(run_dir / "toolkit-recordings"))
            if arc.operation_mode != OperationMode.OFFLINE:
                raise RuntimeError("toolkit did not remain in explicit offline mode")
            env = arc.make(game_id, seed=seed, save_recording=False)
            if env is None or env.observation_space is None:
                raise ValueError(f"could not load local environment: {game_id}")
            observation = env.observation_space
            policy = BoundedExplorer(seed=seed, max_actions=args.max_actions, mode=args.mode)
            started = time.monotonic()
            stop_reason = "action_budget"
            transcript = []
            max_levels_completed = observation.levels_completed
            with (run_dir / "actions.jsonl").open("w", encoding="utf-8") as stream:
                while not policy.is_done([], observation):
                    if time.monotonic() - started >= args.max_seconds:
                        stop_reason = "wall_time_budget"
                        break
                    before = observation
                    decision = policy.decide(before)
                    from arcengine import GameAction
                    observation = env.step(GameAction.from_id(decision.action_id), data=decision.data)
                    if observation is None:
                        raise RuntimeError("environment returned no observation")
                    max_levels_completed = max(max_levels_completed, observation.levels_completed)
                    row = {
                        "step": policy.action_counter,
                        "action_id": decision.action_id,
                        "data": decision.data,
                        "state_before": before.state.name,
                        "state_after": observation.state.name,
                        "levels_completed": observation.levels_completed,
                        "observation_hash": frame_fingerprint(observation),
                    }
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                    stream.flush()
                    transcript.append(row)
                if observation.state.name == "WIN":
                    stop_reason = "win"
            closed = arc.close_scorecard(env.scorecard_id)
            scorecard_values = closed.model_dump() if closed is not None else {}
            local_runs = [run for environment in scorecard_values.get("environments", []) for run in environment.get("runs", [])]
            if len(local_runs) != 1:
                raise RuntimeError("expected exactly one local scorecard run per game/seed")
            local_run = local_runs[0]
            if closed is not None:
                (run_dir / "local-scorecard.json").write_text(closed.model_dump_json(indent=2), encoding="utf-8")
            summary = {
                "evidence_type": args.asset_kind,
                "competition_submission": False,
                "benchmark_score_claim": False,
                "game_id": env.environment_info.game_id,
                "seed": seed,
                "policy": args.mode,
                "actions": policy.action_counter,
                "max_actions": args.max_actions,
                "state": observation.state.name,
                "levels_completed": observation.levels_completed,
                "max_levels_completed_observed": max_levels_completed,
                "win_levels": observation.win_levels,
                "local_toolkit_score_percent": scorecard_values.get("score"),
                "score_scope": "one local public-development game; not a Kaggle leaderboard result" if args.asset_kind == "public_game_local_only" else "toolkit fixture diagnostic only",
                "scorecard_levels_completed": local_run.get("levels_completed"),
                "level_actions": local_run.get("level_actions"),
                "level_scores_percent": local_run.get("level_scores"),
                "level_human_baseline_actions": local_run.get("level_baseline_actions"),
                "resets": local_run.get("resets"),
                "stop_reason": stop_reason,
                "elapsed_seconds": round(time.monotonic() - started, 6),
                "action_transcript_sha256": hashlib.sha256(json.dumps(transcript, sort_keys=True).encode()).hexdigest(),
            }
            (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            summaries.append(summary)
    aggregate = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_type": args.asset_kind,
        "network_guard": "socket connect, connect_ex, create_connection and DNS denied",
        "credentials_used": False,
        "competition_submission": False,
        "benchmark_score_claim": False,
        "dependencies": {package: version(package) for package in ["arc-agi", "arcengine", "numpy", "pydantic"]},
        "source_hashes": source_manifest(assets),
        "policy_sha256": hashlib.sha256((ROOT / "policy.py").read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runs": summaries,
    }
    (output / "aggregate.json").write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aggregate, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environments", type=Path, default=ROOT / "vendor" / "ARC-AGI" / "test_environment_files")
    parser.add_argument("--games", nargs="+", default=["bt11", "bt33"])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--mode", choices=["uniform", "least_visited"], default="uniform")
    parser.add_argument("--max-actions", type=int, default=80)
    parser.add_argument("--max-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset-kind", choices=["toolkit_test_fixture", "public_game_local_only"], default="toolkit_test_fixture")
    args = parser.parse_args()
    if not 0 <= args.max_actions <= 10000:
        parser.error("max-actions must be between zero and 10000")
    if not 0 < args.max_seconds <= 300:
        parser.error("max-seconds must be positive and at most 300")
    try:
        with offline_guard():
            run(args)
    except Exception as error:
        args.output.mkdir(parents=True, exist_ok=True)
        failure = {"status": "failed", "error_type": type(error).__name__, "error": str(error), "competition_submission": False, "benchmark_score_claim": False}
        (args.output / "failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(failure), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
