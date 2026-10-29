"""Fixed transition-memory client using the reviewed gateway transport guards.

Dry-run is the default. This client writes protocol evidence and a genuine public
closed scorecard, never a competition submission artifact or readiness claim.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from arcengine import GameAction
from gateway_runner import (
    GATEWAY_BASE_URL, PUBLIC_HARNESS_KEY, REQUIRED_VERSIONS, SAMPLE_URL,
    SAMPLE_VERSION, GatewayRunError, _gateway_environment, _gateway_transport,
    _make_toolkit_arcade,
)
from policy import frame_fingerprint
from reasoning_policy import ObservationReasoner


ROOT = Path(__file__).resolve().parent
MODE = "transition_memory"
MAX_NOMINAL_PLAY_SECONDS = 30000
MAX_DISCOVERED_GAMES = 1000
SOURCES = ("gateway_memory.py", "gateway_runner.py", "reasoning_policy.py", "policy.py")
CREDENTIAL_KEYS = {
    "apikey", "arcapikey", "xapikey", "authorization", "accesstoken",
    "refreshtoken", "password", "secret", "cookie", "cookies",
}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _state(observation):
    return getattr(observation.state, "name", str(observation.state))


def _public_scorecard(card, card_id):
    """Serialize the returned public value; reject unexpected auth content."""
    if hasattr(card, "model_dump"):
        if getattr(card, "api_key", None) not in (None, ""):
            raise ValueError("closed scorecard contains unexpected authentication content")
        value = card.model_dump(mode="json", exclude={"api_key"}, exclude_none=True)
    elif isinstance(card, dict):
        value = deepcopy(card)
        if value.get("api_key") not in (None, ""):
            raise ValueError("closed scorecard contains unexpected authentication content")
        value.pop("api_key", None)
    else:
        raise TypeError("closed scorecard must be a returned public model or dictionary")

    def inspect(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = "".join(character for character in str(key).lower() if character.isalnum())
                if normalized in CREDENTIAL_KEYS and nested not in (None, "", [], {}):
                    raise ValueError("closed scorecard contains unexpected authentication content")
                inspect(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                inspect(nested)
        elif isinstance(item, str) and PUBLIC_HARNESS_KEY in item:
            raise ValueError("public harness authentication must not be serialized")

    inspect(value)
    if not isinstance(value, dict) or value.get("card_id") != card_id:
        raise ValueError("closed scorecard does not match the opened identifier")
    # Validate JSON compatibility before creating the evidence artifact.
    json.dumps(value, allow_nan=False)
    return value


def run_memory_gateway(*, output, execute_gateway=False, arcade_factory=None,
                       seed=0, max_actions=500, max_seconds=10, clock=time.monotonic):
    """Run one scorecard with transition_memory only and explicit observation.

    Time checks are cooperative between decisions. Toolkit ``make`` performs an
    initial RESET separately; the policy seed does not control gateway game RNG.
    Injected Arcade factories remain inside the same fixed-route HTTP guard.
    """
    if type(execute_gateway) is not bool:
        raise ValueError("execute_gateway must be a boolean")
    if type(seed) is not int or type(max_actions) is not int or not 0 <= max_actions <= 500:
        raise ValueError("seed and bounded max_actions must be integers")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 10:
        raise ValueError("max_seconds must be positive, finite and at most ten")
    if execute_gateway and os.environ.get("KAGGLE_IS_COMPETITION_RERUN", "").strip().lower() not in {"1", "true"}:
        raise PermissionError("gateway execution requires explicit execution and the competition rerun flag")

    destination = Path(output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "dry_run",
        "evidence_type": "memory_gateway_protocol_compatibility_only",
        "hosted_kaggle_validation": False, "competition_submission": False,
        "benchmark_score_claim": False, "environment_seed_controlled": False,
        "sample_url": SAMPLE_URL, "sample_version": SAMPLE_VERSION,
        "gateway_base_url": GATEWAY_BASE_URL, "required_dependencies": REQUIRED_VERSIONS.copy(),
        "source_hashes": {name: _sha(ROOT / name) for name in SOURCES},
        "configuration": {"policy": MODE, "policy_seed": seed, "max_actions": max_actions, "max_seconds": max_seconds},
        "policy_mode_locked": True,
        "observation_contract": "deepcopy initial and returned observations; explicit observe after each logged successful transition",
        "action_count_scope": "policy decisions; attempts logged before step; toolkit make initial RESET separate",
        "time_scope": "cooperative play loop including explicit observe; initialization and closure excluded",
        "total_nominal_play_limit_seconds_exclusive": MAX_NOMINAL_PLAY_SECONDS,
        "discovery_game_limit": MAX_DISCOVERED_GAMES,
        "hard_global_watchdog": False,
        "runs": [], "game_ids": [], "artifacts": {},
        "scorecard_cleanup": {"status": "not_opened"},
    }
    report_path = destination / "report.json"
    if not execute_gateway:
        _write(report_path, report)
        return report

    factory = arcade_factory or _make_toolkit_arcade
    arc = card_id = None
    current_game = current_run = None
    stage = "construct_client"
    open_attempted = False
    (destination / "no-local-environments").mkdir()
    with _gateway_environment(), _gateway_transport():
        try:
            arc = factory(operation_mode="online", arc_base_url=GATEWAY_BASE_URL,
                          arc_api_key=PUBLIC_HARNESS_KEY,
                          environments_dir=str(destination / "no-local-environments"),
                          recordings_dir=str(destination / "toolkit-recordings"))
            stage = "discover_games"
            game_ids = [getattr(item, "game_id", None) for item in arc.get_environments()]
            if not game_ids or any(not isinstance(game, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", game) is None for game in game_ids) or len(set(game_ids)) != len(game_ids):
                raise ValueError("gateway discovery must provide unique valid game identifiers")
            report["game_ids"] = game_ids
            report["nominal_total_play_seconds"] = len(game_ids) * max_seconds
            if len(game_ids) > MAX_DISCOVERED_GAMES or report["nominal_total_play_seconds"] >= MAX_NOMINAL_PLAY_SECONDS:
                raise ValueError("discovered games exceed the bounded nominal play budget")
            stage = "open_scorecard"
            open_attempted = True
            card_id = arc.open_scorecard(tags=["agent", "transition-memory"])
            if not isinstance(card_id, str) or not card_id:
                card_id = None
                raise RuntimeError("gateway returned no usable scorecard identifier")
            report["card_id_sha256"] = hashlib.sha256(card_id.encode()).hexdigest()
            report["scorecard_cleanup"] = {"status": "open"}

            with (destination / "actions.jsonl").open("x", encoding="utf-8") as actions, (destination / "attempts.jsonl").open("x", encoding="utf-8") as attempts:
                for game_id in game_ids:
                    current_game = game_id
                    current_run = {"game_id": game_id, "policy": MODE, "policy_seed": seed,
                                   "status": "running", "actions": 0,
                                   "attempted_actions": 0, "completed_transitions": 0}
                    report["runs"].append(current_run)
                    policy = observation = None
                    started = None
                    try:
                        stage = "make_game"
                        env = arc.make(game_id, seed=seed, scorecard_id=card_id, save_recording=False)
                        if env is None or env.observation_space is None:
                            raise RuntimeError("gateway did not provide an initial observation")
                        observation = deepcopy(env.observation_space)
                        current_run["initial_observation_hash"] = frame_fingerprint(observation)
                        policy = ObservationReasoner(seed=seed, max_actions=max_actions, mode=MODE)
                        maximum_levels = observation.levels_completed
                        started = clock()
                        stop_reason = "action_budget"
                        stage = "play_game"
                        while not policy.is_done([], observation):
                            if clock() - started >= max_seconds:
                                stop_reason = "wall_time_budget"
                                break
                            before = observation
                            stage = "decide"
                            decision = policy.decide(before)
                            attempt = {"game_id": game_id, "step": policy.action_counter,
                                       "action_id": decision.action_id, "data": dict(decision.data),
                                       "state_before": _state(before)}
                            attempts.write(json.dumps(attempt, sort_keys=True) + "\n")
                            attempts.flush()
                            current_run["attempted_actions"] += 1
                            stage = "step"
                            returned = env.step(GameAction.from_id(decision.action_id), data=dict(decision.data))
                            if returned is None:
                                raise RuntimeError("gateway returned no observation after action")
                            observation = deepcopy(returned)
                            maximum_levels = max(maximum_levels, observation.levels_completed)
                            stage = "record_transition"
                            row = {**attempt, "reason": decision.reason,
                                   "available_actions_before": sorted({int(action) for action in before.available_actions}),
                                   "state_after": _state(observation), "levels_completed": observation.levels_completed,
                                   "observation_hash": frame_fingerprint(observation)}
                            actions.write(json.dumps(row, sort_keys=True) + "\n")
                            actions.flush()
                            current_run["completed_transitions"] += 1
                            stage = "observe"
                            policy.observe(before, decision, observation)
                            stage = "play_game"
                        if _state(observation) == "WIN":
                            stop_reason = "win"
                        current_run.update(status="passed", stop_reason=stop_reason,
                                           max_levels_completed_observed=maximum_levels)
                    except BaseException as error:
                        current_run.update(status="failed" if isinstance(error, Exception) else "interrupted",
                                           error_type=type(error).__name__, failure_stage=stage)
                        raise
                    finally:
                        if policy is not None:
                            current_run["actions"] = policy.action_counter
                            current_run["reasoning_stats"] = policy.stats()
                        if observation is not None:
                            current_run.update(state=_state(observation), levels_completed=observation.levels_completed)
                        if started is not None:
                            current_run["elapsed_seconds"] = clock() - started
                    stats = current_run["reasoning_stats"]
                    if not (stats["actions"] == stats["observed_transitions"] == current_run["completed_transitions"] == current_run["actions"] and not stats["pending"]):
                        current_run.update(status="failed", failure_stage="verify_observation_counts")
                        stage = "verify_observation_counts"
                        raise RuntimeError("memory did not consume every completed transition exactly once")
                    current_run = None
                report["status"] = "protocol_completed"
        except Exception as error:
            report.update(status="failed", error_type=type(error).__name__, failure_stage=stage, failure_game_id=current_game)
        except BaseException as error:
            report.update(status="interrupted", error_type=type(error).__name__, failure_stage=stage, failure_game_id=current_game)
            raise
        finally:
            if card_id is not None:
                closed = None
                try:
                    closed = arc.close_scorecard(card_id)
                    if closed is None:
                        raise RuntimeError("gateway returned no closed scorecard")
                    report["scorecard_cleanup"] = {"status": "closed"}
                except Exception as error:
                    report["scorecard_cleanup"] = {"status": "failed", "error_type": type(error).__name__}
                    if report["status"] != "interrupted":
                        report.update(status="failed", error_type=type(error).__name__, failure_stage="close_scorecard", failure_game_id=None)
                if closed is not None:
                    try:
                        public = _public_scorecard(closed, card_id)
                        _write(destination / "closed-scorecard.json", public)
                        report.update(closed_scorecard_file="closed-scorecard.json",
                                      closed_scorecard_sha256=_sha(destination / "closed-scorecard.json"))
                    except Exception as error:
                        report["closed_scorecard_evidence"] = {"status": "failed", "error_type": type(error).__name__}
                        if report["status"] != "interrupted":
                            report.update(status="failed", error_type=type(error).__name__, failure_stage="save_closed_scorecard", failure_game_id=None)
            elif open_attempted:
                report["scorecard_cleanup"] = {"status": "no_scorecard_id"}
            for filename in ("actions.jsonl", "attempts.jsonl", "closed-scorecard.json"):
                if (destination / filename).is_file():
                    report["artifacts"][filename] = _sha(destination / filename)
            _write(report_path, report)
    if report["status"] == "failed":
        raise GatewayRunError(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute-gateway", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-actions", type=int, default=500)
    parser.add_argument("--max-seconds", type=float, default=10)
    args = parser.parse_args()
    try:
        report = run_memory_gateway(output=args.output, execute_gateway=args.execute_gateway,
                                    seed=args.seed, max_actions=args.max_actions, max_seconds=args.max_seconds)
    except GatewayRunError as error:
        print(json.dumps(error.report, indent=2))
        raise SystemExit(1) from error
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
