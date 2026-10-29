"""Bounded, seeded ARC-AGI-3 exploration; no model or game-specific knowledge.

This is an interface baseline. It makes no competitive or novelty claim.
"""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import random
from typing import Any

from arcengine import GameAction, GameState


@dataclass(frozen=True)
class Decision:
    action_id: int
    data: dict[str, int]
    reason: str


def frame_fingerprint(frame: Any) -> str:
    """Hash only observable state, completion count and rendered pixels."""
    pixels = [part.tolist() if hasattr(part, "tolist") else part for part in frame.frame]
    payload = [frame.state.name, frame.levels_completed, pixels]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


class BoundedExplorer:
    def __init__(self, seed: int = 0, max_actions: int = 80, mode: str = "uniform"):
        if isinstance(max_actions, bool) or not isinstance(max_actions, int) or max_actions < 0:
            raise ValueError("max_actions must be a nonnegative integer")
        if mode not in {"uniform", "least_visited"}:
            raise ValueError("mode must be uniform or least_visited")
        self.seed = seed
        self.max_actions = max_actions
        self.mode = mode
        self.action_counter = 0
        self._rng = random.Random(seed)
        self._visits: Counter[tuple[str, int]] = Counter()

    def is_done(self, frames: list[Any], latest_frame: Any) -> bool:
        return self.action_counter >= self.max_actions or latest_frame.state == GameState.WIN

    def decide(self, latest_frame: Any) -> Decision:
        if self.is_done([], latest_frame):
            raise StopIteration("agent is complete or its action budget is exhausted")
        if latest_frame.state in {GameState.NOT_PLAYED, GameState.GAME_OVER}:
            decision = Decision(GameAction.RESET.value, {}, "reset required by observed state")
        else:
            valid = {action.value for action in GameAction if action != GameAction.RESET}
            legal = sorted({int(action) for action in latest_frame.available_actions} & valid)
            if not legal:
                raise ValueError("no supported legal action advertised by environment")
            state_key = frame_fingerprint(latest_frame)
            candidates = legal
            if self.mode == "least_visited":
                minimum = min(self._visits[(state_key, action)] for action in legal)
                candidates = [action for action in legal if self._visits[(state_key, action)] == minimum]
            action_id = self._rng.choice(candidates)
            data = {"x": self._rng.randrange(64), "y": self._rng.randrange(64)} if action_id == 6 else {}
            self._visits[(state_key, action_id)] += 1
            decision = Decision(action_id, data, self.mode)
        self.action_counter += 1
        return decision

    def choose_action(self, frames: list[Any], latest_frame: Any) -> GameAction:
        """Adapter for the public framework's choose_action/is_done protocol.

        GameAction is a mutable enum upstream; this adapter is sequential only.
        The standalone runner passes an independent data dict directly to step.
        """
        decision = self.decide(latest_frame)
        action = GameAction.from_id(decision.action_id)
        if decision.data:
            action.set_data(decision.data)
        action.reasoning = {"policy": decision.reason, "seed": self.seed}
        return action
