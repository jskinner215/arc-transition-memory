"""Independent bounded client for the reviewed ARC-AGI-3 gateway protocol.

Dry-run is the default. This module never writes a competition submission file,
creates credentials or certifies hosted Kaggle readiness. Local tests may inject
an Arcade factory or bridge the pinned toolkit to an in-process Flask server.
"""

import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from arcengine import GameAction
from policy import BoundedExplorer, frame_fingerprint


ROOT = Path(__file__).resolve().parent
GATEWAY_BASE_URL = "http://gateway:8001"
# Public test-harness literal visible in the reviewed official sample notebook.
# This is not a personal API key and is never obtained from a credential file.
PUBLIC_HARNESS_KEY = "test-key-123"
REQUIRED_VERSIONS = {"arc-agi": "0.9.8", "arcengine": "0.9.3"}
SAMPLE_URL = "https://www.kaggle.com/code/inversion/arc3-sample-submission-stochastic-goose"
SAMPLE_VERSION = "306264530"


class GatewayRunError(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__("gateway protocol run failed; inspect the local report")


class GatewayTransportError(ValueError):
    pass


def _validate_request(method, url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "gateway" or parsed.port != 8001 or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GatewayTransportError("request is outside the fixed competition gateway")
    path = parsed.path
    permitted = (
        method == "GET" and (path == "/api/games" or re.fullmatch(r"/api/games/(?!anonkey$)[A-Za-z0-9_-]{1,100}", path))
        or method == "POST" and (path in {"/api/scorecard/open", "/api/scorecard/close", "/api/cmd/RESET"} or re.fullmatch(r"/api/cmd/ACTION[1-7]", path))
    )
    if not permitted:
        raise GatewayTransportError("request is not an allowed game or scorecard operation")


@contextmanager
def _gateway_transport():
    """Restrict toolkit HTTP calls, including discovery, to reviewed API routes."""
    import requests

    underlying_factory = requests.Session
    sessions = []

    class GuardedSession:
        def __init__(self):
            self._session = underlying_factory()
            # Avoid environment proxies and netrc authentication.
            self._session.trust_env = False
            sessions.append(self)

        def __getattr__(self, name):
            return getattr(self._session, name)

        def request(self, method, url, **kwargs):
            _validate_request(method.upper(), url)
            kwargs["allow_redirects"] = False
            response = self._session.request(method, url, **kwargs)
            if 300 <= response.status_code < 400:
                raise GatewayTransportError("gateway redirects are not permitted")
            return response

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def close(self):
            self._session.close()

    def guarded_get(url, **kwargs):
        session = GuardedSession()
        try:
            return session.get(url, **kwargs)
        finally:
            session.close()

    try:
        with patch.object(requests, "Session", GuardedSession), patch.object(requests, "get", guarded_get):
            yield
    finally:
        for session in sessions:
            session.close()


@contextmanager
def _gateway_environment():
    values = {"OPERATION_MODE": "online", "ARC_BASE_URL": GATEWAY_BASE_URL, "ARC_API_KEY": PUBLIC_HARNESS_KEY, "PYTHON_DOTENV_DISABLED": "1"}
    with patch.dict(os.environ, values), patch("dotenv.load_dotenv", return_value=False):
        yield


def _make_toolkit_arcade(**kwargs):
    for package, expected in REQUIRED_VERSIONS.items():
        if version(package) != expected:
            raise RuntimeError("installed toolkit dependencies do not match the reviewed pins")
    # The caller blocks dotenv loading before this import.
    from arc_agi import Arcade, OperationMode

    kwargs["operation_mode"] = OperationMode(kwargs["operation_mode"])
    return Arcade(**kwargs)


def _state(frame):
    return getattr(frame.state, "name", str(frame.state))


def _source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("gateway_runner.py", "policy.py")}


def run_gateway(*, output, execute_gateway=False, arcade_factory=None, policy_factory=BoundedExplorer, seed=0, max_actions=500, max_seconds=10, mode="least_visited", clock=time.monotonic):
    """Run one sequential scorecard only after both explicit execution gates.

    Injected factories receive the same constructor keywords as the pinned
    toolkit. ``actions`` counts policy decisions; toolkit ``make`` performs an
    initial RESET separately. The policy seed does not control gateway game RNG.
    Time limits are cooperative between calls, not a hard per-step watchdog.
    """
    if type(execute_gateway) is not bool:
        raise ValueError("execute_gateway must be a boolean")
    if type(seed) is not int or type(max_actions) is not int or not 0 <= max_actions <= 10000:
        raise ValueError("seed and nonnegative bounded max_actions must be integers")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or not 0 < max_seconds <= 300:
        raise ValueError("max_seconds must be positive, finite and at most 300")
    if mode not in {"uniform", "least_visited"}:
        raise ValueError("unsupported policy mode")
    if execute_gateway and os.environ.get("KAGGLE_IS_COMPETITION_RERUN", "").strip().lower() not in {"1", "true"}:
        raise PermissionError("gateway execution requires KAGGLE_IS_COMPETITION_RERUN and explicit execution")

    destination = Path(output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "dry_run", "evidence_type": "gateway_protocol_compatibility_only",
        "hosted_kaggle_validation": False, "competition_submission": False, "benchmark_score_claim": False,
        "sample_url": SAMPLE_URL, "sample_version": SAMPLE_VERSION,
        "gateway_base_url": GATEWAY_BASE_URL, "required_dependencies": REQUIRED_VERSIONS.copy(),
        "source_hashes": _source_hashes(), "configuration": {"policy": mode, "policy_seed": seed, "max_actions": max_actions, "max_seconds": max_seconds},
        "action_count_scope": "policy decisions; toolkit make performs an initial RESET separately",
        "environment_seed_controlled": False, "runs": [], "game_ids": [],
        "scorecard_cleanup": {"status": "not_opened"},
    }
    report_path = destination / "report.json"
    if not execute_gateway:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report

    factory = arcade_factory or _make_toolkit_arcade
    arc = None
    card_id = None
    open_attempted = False
    stage = "construct_client"
    current_game = None
    (destination / "no-local-environments").mkdir()
    with _gateway_environment(), (_gateway_transport() if arcade_factory is None else nullcontext()):
        try:
            arc = factory(operation_mode="online", arc_base_url=GATEWAY_BASE_URL, arc_api_key=PUBLIC_HARNESS_KEY, environments_dir=str(destination / "no-local-environments"), recordings_dir=str(destination / "toolkit-recordings"))
            stage = "discover_games"
            environments = list(arc.get_environments())
            game_ids = [getattr(environment, "game_id", None) for environment in environments]
            if not game_ids or any(not isinstance(game_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", game_id) is None for game_id in game_ids) or len(set(game_ids)) != len(game_ids):
                raise ValueError("gateway discovery must provide unique valid game identifiers")
            report["game_ids"] = game_ids
            stage = "open_scorecard"
            open_attempted = True
            card_id = arc.open_scorecard(tags=["agent", "bounded-exploration"])
            if not isinstance(card_id, str) or not card_id:
                card_id = None
                raise RuntimeError("gateway returned no usable scorecard identifier")
            with (destination / "actions.jsonl").open("x", encoding="utf-8") as actions:
                for game_id in game_ids:
                    current_game = game_id
                    stage = "make_game"
                    env = arc.make(game_id, seed=seed, scorecard_id=card_id, save_recording=False)
                    if env is None or env.observation_space is None:
                        raise RuntimeError("gateway did not provide an initial observation")
                    observation = env.observation_space
                    policy = policy_factory(seed=seed, max_actions=max_actions, mode=mode)
                    started = clock()
                    stop_reason = "action_budget"
                    stage = "play_game"
                    while not policy.is_done([], observation):
                        if clock() - started >= max_seconds:
                            stop_reason = "wall_time_budget"
                            break
                        before = observation
                        decision = policy.decide(before)
                        observation = env.step(GameAction.from_id(decision.action_id), data=dict(decision.data))
                        if observation is None:
                            raise RuntimeError("gateway returned no observation after action")
                        row = {"game_id": game_id, "step": policy.action_counter, "action_id": decision.action_id, "data": dict(decision.data), "state_before": _state(before), "state_after": _state(observation), "observation_hash": frame_fingerprint(observation)}
                        actions.write(json.dumps(row, sort_keys=True) + "\n")
                        actions.flush()
                    if _state(observation) == "WIN":
                        stop_reason = "win"
                    report["runs"].append({"game_id": game_id, "policy": mode, "policy_seed": seed, "actions": policy.action_counter, "state": _state(observation), "levels_completed": observation.levels_completed, "stop_reason": stop_reason})
            report["status"] = "protocol_completed"
        except Exception as error:
            report.update(status="failed", error_type=type(error).__name__, failure_stage=stage, failure_game_id=current_game)
        finally:
            if card_id is not None:
                try:
                    if arc.close_scorecard(card_id) is None:
                        raise RuntimeError("gateway returned no closed scorecard")
                    report["scorecard_cleanup"] = {"status": "closed"}
                except Exception as error:
                    report["scorecard_cleanup"] = {"status": "failed", "error_type": type(error).__name__}
                    if report["status"] != "failed":
                        report.update(status="failed", error_type=type(error).__name__, failure_stage="close_scorecard", failure_game_id=None)
            elif open_attempted:
                report["scorecard_cleanup"] = {"status": "no_scorecard_id"}
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
    parser.add_argument("--mode", choices=["uniform", "least_visited"], default="least_visited")
    args = parser.parse_args()
    try:
        report = run_gateway(output=args.output, execute_gateway=args.execute_gateway, seed=args.seed, max_actions=args.max_actions, max_seconds=args.max_seconds, mode=args.mode)
    except GatewayRunError as error:
        print(json.dumps(error.report, indent=2))
        raise SystemExit(1) from error
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
