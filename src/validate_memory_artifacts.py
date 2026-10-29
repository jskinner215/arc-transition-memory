"""Read-only validation of local pinned-toolkit memory evidence, never parquet.

The JSON schema and score calculations follow arc-agi 0.9.8. Passing establishes
local consistency with supplied source hashes, not hosted Kaggle acceptance.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
REQUIRED_SOURCES = {"gateway_memory.py", "gateway_runner.py", "policy.py", "reasoning_policy.py"}
REQUIRED_DEPENDENCIES = {"arc-agi": "0.9.8", "arcengine": "0.9.3"}
ARTIFACTS = {"actions.jsonl", "attempts.jsonl", "closed-scorecard.json"}
STATES = {"NOT_PLAYED", "NOT_FINISHED", "GAME_OVER", "WIN"}
CARD_FIELDS = {
    "source_url", "tags", "opaque", "card_id", "api_key", "score", "environments",
    "tags_scores", "competition_mode", "total_environments_completed", "total_environments",
    "total_levels_completed", "total_levels", "total_actions",
}
ENV_FIELDS = {"id", "runs", "score", "actions", "levels_completed", "completed", "level_count", "resets"}
RUN_FIELDS = {
    "id", "guid", "score", "levels_completed", "actions", "resets", "state", "completed",
    "level_scores", "level_actions", "level_baseline_actions", "number_of_levels",
    "number_of_environments", "message",
}


class ArtifactValidationError(ValueError):
    pass


def _check(condition, message):
    if not condition:
        raise ArtifactValidationError(message)


def _int(value, label, maximum=None):
    _check(type(value) is int and value >= 0 and (maximum is None or value <= maximum), f"invalid {label}")
    return value


def _number(value, label, maximum=None):
    _check(type(value) in (int, float) and math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum), f"invalid {label}")
    return value


def _close(actual, expected, label):
    _number(actual, label)
    _check(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9), f"inconsistent {label}")


def _object(value, allowed, label):
    _check(isinstance(value, dict) and set(value) <= allowed, f"unsupported {label} schema")


def assert_no_credentials(value):
    """Reject nonempty authentication content without echoing its value."""
    keys = {"apikey", "arcapikey", "xapikey", "authorization", "accesstoken", "refreshtoken", "password", "secret", "cookie", "cookies"}
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in keys:
                _check(nested is None or nested == "" or nested == [] or nested == {}, "authentication content is not permitted in evidence")
            assert_no_credentials(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            assert_no_credentials(nested)
    elif isinstance(value, str):
        _check("test-key-123" not in value, "public harness authentication is not permitted in evidence")
    elif type(value) is float:
        _check(math.isfinite(value), "nonfinite evidence value")


def _reasoning(row, required=False):
    stats = row.get("reasoning_stats")
    if stats is None:
        _check(not required, "missing reasoning statistics")
        return
    _check(isinstance(stats, dict), "invalid reasoning statistics")
    _int(stats.get("actions"), "reasoning action count", 500)
    _int(stats.get("observed_transitions"), "reasoning transition count", 500)
    _check(stats.get("actions") == stats.get("observed_transitions") == row["actions"], "reasoning transition counts differ")
    _check(stats.get("pending") is False, "unconsumed reasoning observation")
    for name, limit in (("states", 500), ("edges", 500), ("max_edges_inspected", 64)):
        _int(stats.get(name), "reasoning " + name, limit)
    for name in ("noops", "deaths", "progress_events", "plans_selected", "state_capacity_skips", "edge_capacity_skips"):
        if name in stats:
            _int(stats[name], "reasoning " + name)
    if required:
        _check(stats.get("mode") == "transition_memory", "reasoning mode differs from fixed memory policy")


def validate_closed_scorecard(card, runs, expected_game_ids, *, competition_mode=None):
    """Validate genuine public scorecard JSON against completed local run rows.

    This does not infer closure or authenticity from a JSON object alone. The
    enclosing producer report and its known source/artifact hashes bind those.
    Initial full RESET starts at zero actions in the pinned local server; later
    RESET commands count as actions. No speculative action offset is accepted.
    """
    assert_no_credentials(card)
    assert_no_credentials(runs)
    _object(card, CARD_FIELDS, "closed scorecard")
    _check(isinstance(card.get("card_id"), str) and bool(card["card_id"]), "missing scorecard identifier")
    _check(card.get("api_key") is None or card.get("api_key") == "", "invalid public scorecard API-key field")
    _check(card.get("competition_mode") is None or type(card.get("competition_mode")) is bool, "invalid competition mode")
    if competition_mode is not None:
        _check(card.get("competition_mode") is competition_mode, "scorecard competition mode differs")
    _check(isinstance(expected_game_ids, list) and bool(expected_game_ids) and all(isinstance(game, str) and game for game in expected_game_ids), "invalid expected game identifiers")
    _check(len(set(expected_game_ids)) == len(expected_game_ids), "duplicate expected game identifier")
    _check(isinstance(runs, list) and len(runs) == len(expected_game_ids), "run coverage differs")
    by_game = {}
    for row in runs:
        _check(isinstance(row, dict) and row.get("game_id") in expected_game_ids and row["game_id"] not in by_game, "duplicate or unexpected run")
        _int(row.get("actions"), "policy action count", 500)
        _int(row.get("completed_transitions"), "completed transition count", 500)
        _check(row.get("completed_transitions") == row["actions"], "incomplete policy transitions")
        _int(row.get("levels_completed"), "observed completion count", 254)
        _reasoning(row)
        by_game[row["game_id"]] = row
    environments = card.get("environments")
    _check(isinstance(environments, list) and len(environments) == len(expected_game_ids), "scorecard environment coverage differs")
    seen, scores, total_actions, total_levels, completed, level_count = set(), [], 0, 0, 0, 0
    for environment in environments:
        _object(environment, ENV_FIELDS, "environment")
        game_id = environment.get("id")
        _check(isinstance(game_id, str) and game_id in by_game and game_id not in seen, "duplicate or unexpected scorecard environment")
        seen.add(game_id)
        row = by_game[game_id]
        local_runs = environment.get("runs")
        _check(isinstance(local_runs, list) and len(local_runs) == 1, "expected exactly one scorecard run per game")
        run = local_runs[0]
        _object(run, RUN_FIELDS, "environment run")
        _check(run.get("id") in (None, game_id), "run identifier differs")
        _check(isinstance(run.get("guid"), str) and bool(run["guid"]), "missing run identifier")
        _int(run.get("actions"), "scorecard action count", 500)
        _check(run["actions"] == row["actions"], "scorecard and policy action counts differ")
        _int(run.get("levels_completed"), "scorecard completion count", 254)
        _check(run["levels_completed"] == row["levels_completed"], "scorecard and observed completion counts differ")
        _check(run.get("state") in STATES and type(run.get("completed")) is bool, "invalid scorecard state")
        _check(run["completed"] == (run["state"] == "WIN"), "scorecard completion flag differs")
        # The SDK can retain GAME_OVER after a later NOT_FINISHED observation.
        if row.get("state") == "WIN":
            _check(run["completed"], "observed win absent from scorecard")
        arrays = [run.get(name) for name in ("level_actions", "level_scores", "level_baseline_actions")]
        _check(all(isinstance(values, list) for values in arrays) and len({len(values) for values in arrays}) == 1, "missing or uneven per-level score evidence")
        actions, recorded_scores, baselines = arrays
        _check(run["levels_completed"] <= len(actions), "completion count exceeds levels")
        _check(all(type(value) is int and value >= 0 for value in actions + baselines), "unverifiable per-level action evidence")
        _check(sum(actions) == run["actions"], "per-level and total action counts differ")
        expected_scores = [min(115.0, (human / count) ** 2 * 100) if index < run["levels_completed"] and count > 0 else 0.0 for index, (count, human) in enumerate(zip(actions, baselines))]
        for actual, expected in zip(recorded_scores, expected_scores):
            _number(actual, "per-level score", 115)
            _close(actual, expected, "per-level score")
        weights = list(range(1, len(actions) + 1))
        score = min(sum(value * weight for value, weight in zip(expected_scores, weights)) / sum(weights), 100 * sum(weight for value, weight in zip(expected_scores, weights) if value > 0) / sum(weights)) if weights else 0.0
        _number(run.get("score"), "run score", 100)
        _close(run["score"], score, "run score")
        _number(environment.get("score"), "environment score", 100)
        _close(environment.get("score"), score, "environment score")
        resets = _int(run.get("resets"), "reset count", run["actions"])
        for name, expected in (("actions", run["actions"]), ("levels_completed", run["levels_completed"]), ("level_count", len(actions)), ("resets", resets)):
            _int(environment.get(name), "environment " + name)
            _check(environment.get(name) == expected, "environment computed totals differ")
        _check(environment.get("completed") is run["completed"], "environment completion flag differs")
        scores.append(score)
        total_actions += run["actions"]
        total_levels += run["levels_completed"]
        completed += int(run["completed"])
        level_count += len(actions)
    _number(card.get("score"), "scorecard score", 100)
    _close(card["score"], sum(scores) / len(scores), "scorecard score")
    for name, expected in (("total_environments", len(seen)), ("total_environments_completed", completed), ("total_levels_completed", total_levels), ("total_levels", level_count), ("total_actions", total_actions)):
        _int(card.get(name), "scorecard " + name)
        _check(card.get(name) == expected, "scorecard computed totals differ")
    _check(isinstance(card.get("tags_scores"), list), "missing scorecard tag-score list")
    for tag_score in card["tags_scores"]:
        _object(tag_score, RUN_FIELDS, "tag score")
        _number(tag_score.get("score"), "tag score", 100)
        _int(tag_score.get("actions"), "tag action count")
        _int(tag_score.get("levels_completed"), "tag completion count")
    return {"status": "passed", "evidence_type": "local_pinned_closed_scorecard_only", "games": len(seen), "actions": total_actions, "levels_completed": total_levels, "local_toolkit_score_percent": card["score"], "competition_submission": False}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _unique_object(pairs):
    value = {}
    for key, nested in pairs:
        _check(key not in value, "duplicate evidence JSON field")
        value[key] = nested
    return value


def _nonfinite_constant(value):
    raise ArtifactValidationError("nonfinite evidence JSON")


def _read(path):
    _check(path.is_file() and path.stat().st_size <= 256 * 1024 * 1024, "missing or oversized evidence file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_nonfinite_constant, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as error:
        raise ArtifactValidationError("invalid evidence JSON") from error
    assert_no_credentials(value)
    return value


def _lines(path):
    _check(path.is_file() and path.stat().st_size <= 256 * 1024 * 1024, "missing or oversized transcript")
    try:
        rows = [json.loads(line, parse_constant=_nonfinite_constant, object_pairs_hook=_unique_object) for line in path.read_text(encoding="utf-8").splitlines()]
    except (ValueError, UnicodeError) as error:
        raise ArtifactValidationError("invalid transcript JSON") from error
    assert_no_credentials(rows)
    return rows


def validate_memory_artifacts(directory, *, expected_sources=None, expected_game_ids=None, source_root=None):
    """Validate the fixed-memory gateway's completed local evidence directory."""
    directory, source_root = Path(directory).resolve(), Path(source_root or ROOT).resolve()
    report_path = (directory / "report.json").resolve()
    _check(report_path.is_relative_to(directory), "report escapes evidence directory")
    report = _read(report_path)
    _check(isinstance(report, dict) and report.get("status") == "protocol_completed", "gateway report did not complete")
    _check(report.get("evidence_type") == "memory_gateway_protocol_compatibility_only", "unsupported evidence scope")
    for flag in ("hosted_kaggle_validation", "competition_submission", "benchmark_score_claim"):
        _check(report.get(flag) is False, "unsupported hosted or submission claim")
    _check(report.get("required_dependencies") == REQUIRED_DEPENDENCIES and report.get("gateway_base_url") == "http://gateway:8001", "gateway runtime contract differs")
    configuration = report.get("configuration", {})
    _check(isinstance(configuration, dict), "invalid memory configuration")
    _check(configuration.get("policy") == "transition_memory" and report.get("policy_mode_locked") is True, "memory policy is not fixed")
    _check(type(configuration.get("policy_seed")) is int, "invalid policy seed")
    budget = _int(configuration.get("max_actions"), "action budget", 500)
    seconds = _number(configuration.get("max_seconds"), "cooperative time budget", 10)
    _check(seconds > 0, "invalid cooperative time budget")
    sources = report.get("source_hashes")
    _check(isinstance(sources, dict) and REQUIRED_SOURCES <= set(sources), "missing execution source provenance")
    if expected_sources is not None:
        _check(sources == expected_sources, "execution sources differ from expected provenance")
    for name, digest in sources.items():
        _check(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_]+\.py", name) is not None and _digest(digest), "invalid source provenance entry")
        path = (source_root / name).resolve()
        _check(path.is_relative_to(source_root) and path.is_file() and path.stat().st_size <= 4 * 1024 * 1024 and _sha(path) == digest, "execution source hash differs")
    artifacts = report.get("artifacts")
    _check(isinstance(artifacts, dict) and set(artifacts) == ARTIFACTS, "local artifact inventory differs")
    for name, digest in artifacts.items():
        path = (directory / name).resolve()
        _check(path.is_relative_to(directory) and path.is_file() and path.stat().st_size <= 256 * 1024 * 1024 and _digest(digest) and _sha(path) == digest, "local artifact hash differs")
    _check(report.get("closed_scorecard_file") == "closed-scorecard.json" and report.get("closed_scorecard_sha256") == artifacts["closed-scorecard.json"], "closed-scorecard binding differs")
    card = _read(directory / "closed-scorecard.json")
    _check(isinstance(card, dict), "invalid closed scorecard JSON")
    _check(isinstance(card.get("card_id"), str) and report.get("card_id_sha256") == hashlib.sha256(card["card_id"].encode()).hexdigest(), "opened and closed scorecard identifiers differ")
    game_ids, runs = report.get("game_ids"), report.get("runs")
    _check(isinstance(game_ids, list) and 0 < len(game_ids) <= 1000, "invalid discovered game list")
    if expected_game_ids is not None:
        _check(set(game_ids) == set(expected_game_ids), "discovered games differ from expected provenance")
    scorecard_result = validate_closed_scorecard(card, runs, game_ids, competition_mode=True)
    actions, attempts = _lines(directory / "actions.jsonl"), _lines(directory / "attempts.jsonl")
    _check(len(actions) == len(attempts) == scorecard_result["actions"], "transcript action counts differ")
    grouped = {game: [] for game in game_ids}
    for action, attempt in zip(actions, attempts):
        _check(isinstance(action, dict) and isinstance(attempt, dict) and action.get("game_id") in grouped, "unexpected transcript game")
        shared_keys = ("game_id", "step", "action_id", "data", "state_before")
        _check(json.dumps({key: action.get(key) for key in shared_keys}, sort_keys=True) == json.dumps({key: attempt.get(key) for key in shared_keys}, sort_keys=True), "attempt and transition differ")
        game = action["game_id"]
        _int(action.get("step"), "transcript step", 500)
        _check(action.get("step") == len(grouped[game]) + 1, "nonsequential transcript steps")
        _check(action.get("state_before") in STATES - {"WIN"} and action.get("state_after") in STATES, "invalid transcript state")
        if grouped[game]:
            _check(grouped[game][-1]["state_after"] == action["state_before"], "discontinuous transcript states")
        action_id, data = action.get("action_id"), action.get("data")
        _check(type(action_id) is int and 0 <= action_id <= 7 and isinstance(data, dict), "invalid transcript command")
        legal = action.get("available_actions_before")
        _check(isinstance(legal, list) and all(type(value) is int and 0 <= value <= 7 for value in legal) and legal == sorted(set(legal)), "invalid advertised legal actions")
        if action["state_before"] in {"NOT_PLAYED", "GAME_OVER"}:
            _check(action_id == 0, "required observed reset was skipped")
        if action_id == 0:
            _check(action["state_before"] in {"NOT_PLAYED", "GAME_OVER"}, "reset lacks an observed required state")
        else:
            _check(action_id in legal, "command was not advertised legal")
        if action_id == 6:
            _check(set(data) == {"x", "y"} and all(type(value) is int and 0 <= value <= 63 for value in data.values()), "invalid click coordinates")
        else:
            _check(not data, "unexpected simple-command data")
        _int(action.get("levels_completed"), "transcript completion count", 254)
        _check(_digest(action.get("observation_hash")), "missing observation fingerprint")
        grouped[game].append(action)
    for row in runs:
        _check(row.get("status") == "passed" and row.get("policy") == "transition_memory" and row.get("policy_seed") == configuration["policy_seed"], "run policy or completion differs")
        _int(row.get("attempted_actions"), "attempted action count", 500)
        _check(row["actions"] == row["attempted_actions"] == len(grouped[row["game_id"]]) <= budget, "run transcript count differs")
        _check(row.get("state") in STATES, "invalid observed run state")
        _reasoning(row, required=True)
        stop = row.get("stop_reason")
        _check(stop in {"action_budget", "wall_time_budget", "win"}, "unknown stop reason")
        _check(stop != "action_budget" or row["actions"] == budget, "action-budget stop occurred early")
        _check(stop != "win" or row.get("state") == "WIN", "win stop lacks an observed win")
        _number(row.get("elapsed_seconds"), "elapsed play time")
        if grouped[row["game_id"]]:
            last = grouped[row["game_id"]][-1]
            _check(last["state_after"] == row.get("state") and last["levels_completed"] == row["levels_completed"], "final transcript and run differ")
    for environment in card["environments"]:
        reset_count = sum(action["action_id"] == 0 for action in grouped[environment["id"]])
        _check(environment["runs"][0]["resets"] == reset_count, "scorecard and logged reset counts differ")
    cleanup = report.get("scorecard_cleanup")
    _check(isinstance(cleanup, dict) and cleanup.get("status") == "closed", "scorecard closure was not confirmed")
    return {**scorecard_result, "evidence_type": "local_memory_gateway_artifacts_only", "artifact_hashes": artifacts.copy(), "source_hashes": sources.copy(), "hosted_kaggle_validation": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    try:
        result = validate_memory_artifacts(args.directory, source_root=args.source_root)
    except (ArtifactValidationError, OSError, TypeError, KeyError) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from error
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
