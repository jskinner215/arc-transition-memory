"""Matched Linux public-game evaluation, preserving the original baseline."""

import argparse
import copy
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import random
import time
from unittest.mock import patch

from policy import BoundedExplorer, frame_fingerprint
from run_offline import offline_guard


ROOT = Path(__file__).resolve().parent
POLICIES = ["uniform", "least_visited", "candidate_uniform", "transition_memory", "frontier_plan"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def initial_fingerprint(frame):
    payload = {
        "state_levels_and_frame_sequence": frame_fingerprint(frame),
        "available_actions": sorted({int(action) for action in frame.available_actions}),
        "win_levels": int(frame.win_levels),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def snapshot(frame, step):
    images = frame.frame
    image = images[-1] if len(images) else []
    return {
        "step": step, "state": frame.state.name, "levels_completed": frame.levels_completed,
        "available_actions": [int(value) for value in frame.available_actions],
        "final_image": image.tolist() if hasattr(image, "tolist") else copy.deepcopy(image),
    }


def make_policy(name, seed, max_actions):
    if name in {"uniform", "least_visited"}:
        return BoundedExplorer(seed=seed, max_actions=max_actions, mode=name)
    from reasoning_policy import ObservationReasoner
    return ObservationReasoner(seed=seed, max_actions=max_actions, mode=name)


def evaluate(game, seed, name, args):
    directory = args.output / f"{game}-{name}-seed{seed}"
    owns_directory = False
    result = {
        "game": game, "seed": seed, "policy": name, "status": "running",
        "evidence_type": "public_game_local_linux_only", "competition_submission": False,
        "max_actions": args.max_actions, "max_seconds_cooperative": args.max_seconds,
        "scorecard_cleanup": {"status": "not_opened"},
    }
    arc = env = policy = card_id = None
    rows = []
    snapshots = []
    closed = None
    started = None
    stage = "initialize"
    try:
        directory.mkdir(exist_ok=False)
        owns_directory = True
        from arc_agi import Arcade, OperationMode
        from arcengine import GameAction
        import numpy as np
        random.seed(seed)
        np.random.seed(seed)
        arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(args.assets), recordings_dir=str(directory / "toolkit-recordings"))
        assert arc.operation_mode == OperationMode.OFFLINE
        stage = "open_scorecard"
        result["scorecard_cleanup"] = {"status": "opening"}
        card_id = arc.open_scorecard()
        if not isinstance(card_id, str) or not card_id:
            card_id = None
            result["scorecard_cleanup"] = {"status": "no_identifier"}
            raise RuntimeError("local scorecard did not return an identifier")
        result["scorecard_cleanup"] = {"status": "open"}
        stage = "make_game"
        env = arc.make(game, seed=seed, scorecard_id=card_id, save_recording=False)
        if env is None or env.observation_space is None:
            raise RuntimeError("local environment did not return an initial observation")
        # Local toolkit observations may share game-owned pixel buffers or legal
        # action lists. Detach every response, as a serialized HTTP response does,
        # before any policy, logging or next environment step can retain it.
        observation = copy.deepcopy(env.observation_space)
        result["game_id"] = env.environment_info.game_id
        if result["game_id"] != args.expected_game_ids[game]:
            raise RuntimeError("loaded game version differs from the allowlisted metadata")
        result["initial_frame_hash"] = frame_fingerprint(observation)
        result["initial_observation_hash"] = initial_fingerprint(observation)
        match_key = f"{game}:seed{seed}"
        canonical_initial = args.initial_observations.setdefault(match_key, result["initial_observation_hash"])
        result["matched_initial_observation"] = result["initial_observation_hash"] == canonical_initial
        if not result["matched_initial_observation"]:
            raise RuntimeError("initial observation differs across policies for this game/seed")
        snapshots.append(snapshot(observation, 0))
        policy = make_policy(name, seed, args.max_actions)
        maximum_levels = observation.levels_completed
        stop = "action_budget"
        started = time.monotonic()
        stage = "play"
        with (directory / "actions.jsonl").open("x", encoding="utf-8") as stream, (directory / "attempts.jsonl").open("x", encoding="utf-8") as attempts:
            while not policy.is_done([], observation):
                if time.monotonic() - started >= args.max_seconds:
                    stop = "wall_time_budget"
                    break
                before = observation
                stage = "decide"
                decision = policy.decide(before)
                attempts.write(json.dumps({"step": policy.action_counter, "action_id": decision.action_id, "data": dict(decision.data), "state_before": before.state.name}, sort_keys=True) + "\n")
                attempts.flush()
                stage = "step"
                response = env.step(GameAction.from_id(decision.action_id), data=dict(decision.data))
                if response is None:
                    raise RuntimeError("local environment returned no observation after action")
                observation = copy.deepcopy(response)
                maximum_levels = max(maximum_levels, observation.levels_completed)
                stage = "record_transition"
                row = {
                    "step": policy.action_counter, "action_id": decision.action_id,
                    "data": dict(decision.data), "reason": decision.reason,
                    "state_before": before.state.name, "state_after": observation.state.name,
                    "available_actions_before": sorted({int(action) for action in before.available_actions}),
                    "levels_completed": observation.levels_completed,
                    "observation_hash": frame_fingerprint(observation),
                }
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                rows.append(row)
                if hasattr(policy, "observe"):
                    stage = "observe"
                    policy.observe(before, decision, observation)
                stage = "play"
                if len(snapshots) < 7 and (policy.action_counter <= 4 or observation.levels_completed > before.levels_completed):
                    snapshots.append(snapshot(observation, policy.action_counter))
            if observation.state.name == "WIN":
                stop = "win"
        snapshots.append(snapshot(observation, policy.action_counter))
        result.update(
            status="passed", actions=policy.action_counter, state=observation.state.name,
            levels_completed=observation.levels_completed, max_levels_completed_observed=maximum_levels,
            win_levels=observation.win_levels, stop_reason=stop,
            elapsed_seconds=time.monotonic() - started,
        )
        if hasattr(policy, "stats"):
            result["reasoning_stats"] = policy.stats()
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error), failure_stage=stage)
        if policy is not None:
            result["actions"] = policy.action_counter
    except BaseException as error:
        result.update(status="interrupted", error_type=type(error).__name__, failure_stage=stage)
        if policy is not None:
            result["actions"] = policy.action_counter
        raise
    finally:
        result["completed_transitions"] = len(rows)
        if card_id is not None:
            try:
                closed = arc.close_scorecard(card_id)
                if closed is None:
                    raise RuntimeError("local scorecard close returned no scorecard")
                result["scorecard_cleanup"] = {"status": "closed"}
                card = closed.model_dump()
                local_runs = [run for environment in card["environments"] for run in environment["runs"]]
                if env is not None and len(local_runs) != 1:
                    raise RuntimeError("expected one scorecard run per case")
                write(directory / "local-scorecard.json", card)
                if env is not None:
                    local_run = local_runs[0]
                    result.update(
                        local_toolkit_score_percent=card["score"],
                        scorecard_levels_completed=local_run["levels_completed"],
                        level_actions=local_run["level_actions"], level_scores_percent=local_run["level_scores"],
                        level_human_baseline_actions=local_run["level_baseline_actions"], resets=local_run["resets"],
                        scorecard_actions=local_run["actions"],
                    )
            except Exception as error:
                result.update(status="failed", close_error_type=type(error).__name__, close_error=str(error))
                if result["scorecard_cleanup"]["status"] != "closed":
                    result["scorecard_cleanup"] = {"status": "failed"}
        result["action_transcript_sha256"] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        core = [{key: row[key] for key in ["step", "action_id", "data", "state_before", "state_after", "levels_completed", "observation_hash"]} for row in rows]
        result["baseline_compatible_transcript_sha256"] = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
        if owns_directory:
            with gzip.open(directory / "observation-snapshots.json.gz", "wt", encoding="utf-8") as stream:
                json.dump(snapshots, stream, separators=(",", ":"))
            write(directory / "summary.json", result)
    return result


def frozen_fingerprint(protocol, manifest, assets):
    return {
        "sources_sha256": {name: sha(ROOT / name) for name in protocol["sources_sha256"]},
        "asset_manifest_sha256": sha(ROOT / "assets/public-assets-manifest.json"),
        "asset_files_sha256": {row["path"]: sha(assets / row["path"]) for row in manifest["files"]},
        "asset_inventory": sorted(path.relative_to(assets).as_posix() for path in assets.rglob("*") if path.is_file() and path.suffix in {".py", ".json"}),
        "runtime_python": platform.python_version(),
        "runtime_packages": {name: version(name) for name in protocol["runtime_packages"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--assets", type=Path, default=ROOT / "assets/supplied-archive/environment_files")
    parser.add_argument("--games", nargs="+")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=POLICIES)
    parser.add_argument("--max-actions", type=int, default=500)
    parser.add_argument("--max-seconds", type=float, default=10)
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("this matched protocol requires Linux")
    args.output = args.output.resolve()
    args.assets = args.assets.resolve()
    if not args.output.is_relative_to(ROOT / "evidence") or not args.output.name.startswith("reasoning-"):
        parser.error("choose a fresh evidence/reasoning-* output directory")
    protocol = json.loads(args.protocol.read_text())
    if platform.python_version() != protocol["runtime_python"]:
        parser.error("Python version differs from the frozen protocol")
    args.games = args.games or protocol["games"]
    if not set(args.games).issubset(protocol["games"]) or not set(args.seeds).issubset(protocol["seeds"]) or not set(args.policies).issubset(protocol["policies"]):
        parser.error("selection is outside the frozen protocol")
    if any(len(values) != len(set(values)) for values in [args.games, args.seeds, args.policies]):
        parser.error("duplicate game/seed/policy selections are not allowed")
    if args.max_actions != protocol["max_actions"] or args.max_seconds != protocol["max_seconds_cooperative"]:
        parser.error("budgets differ from the frozen protocol")
    for relative, expected in protocol["sources_sha256"].items():
        if sha(ROOT / relative) != expected:
            parser.error("source changed after protocol freeze: " + relative)
    manifest_path = ROOT / "assets/public-assets-manifest.json"
    if sha(manifest_path) != protocol["asset_manifest_sha256"]:
        parser.error("asset manifest changed after protocol freeze")
    manifest = json.loads(manifest_path.read_text())
    for asset in manifest["files"]:
        if sha(args.assets / asset["path"]) != asset["sha256"]:
            parser.error("public asset differs from allowlist")
    expected_paths = {asset["path"] for asset in manifest["files"] if Path(asset["path"]).suffix in {".py", ".json"}}
    actual_paths = {path.relative_to(args.assets).as_posix() for path in args.assets.rglob("*") if path.is_file() and path.suffix in {".py", ".json"}}
    if actual_paths != expected_paths:
        parser.error("asset source/metadata inventory differs from allowlist")
    args.expected_game_ids = {game["id"]: json.loads((args.assets / game["metadata"]).read_text())["game_id"] for game in manifest["games"]}
    args.initial_observations = {}
    packages = {name: version(name) for name in protocol["runtime_packages"]}
    if packages != protocol["runtime_packages"]:
        parser.error("runtime dependencies differ from the frozen protocol")
    before_fingerprint = frozen_fingerprint(protocol, manifest, args.assets)
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": sha(args.protocol), "sources_sha256": protocol["sources_sha256"],
        "runtime": {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(), "packages": packages},
        "selection": {"games": args.games, "seeds": args.seeds, "policies": args.policies},
        "evidence_type": "public_game_local_linux_only", "competition_submission": False,
        "credentials_used": False, "network_guard": "process-local connections and DNS denied during all environment execution",
        "frozen_before": before_fingerprint,
        "runs": [],
    }
    current_case = None
    try:
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}), offline_guard():
            for seed in args.seeds:
                for index, game in enumerate(args.games):
                    shift = (index + seed) % len(args.policies)
                    order = args.policies[shift:] + args.policies[:shift]
                    for name in order:
                        current_case = {"game": game, "seed": seed, "policy": name}
                        try:
                            result = evaluate(game, seed, name, args)
                        except Exception as error:
                            result = {**current_case, "status": "failed", "failure_stage": "unexpected_case_or_evidence_error", "error_type": type(error).__name__, "error": str(error)}
                        report["runs"].append(result)
                        write(args.output / "partial-aggregate.json", report)
                        print(json.dumps({key: result.get(key) for key in ["game", "seed", "policy", "status", "actions", "local_toolkit_score_percent", "stop_reason"]}), flush=True)
                        current_case = None
    except BaseException as error:
        report["execution_error"] = {"type": type(error).__name__, "case": current_case}
        raise
    finally:
        try:
            report["frozen_after"] = frozen_fingerprint(protocol, manifest, args.assets)
            report["post_validation_passed"] = report["frozen_after"] == before_fingerprint
        except Exception as error:
            report["post_validation_passed"] = False
            report["post_validation_error"] = type(error).__name__
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "passed" if not report.get("execution_error") and report["post_validation_passed"] and all(row["status"] == "passed" for row in report["runs"]) else "failed"
        write(args.output / "aggregate.json", report)
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
