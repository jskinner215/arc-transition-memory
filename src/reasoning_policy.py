"""Bounded online transition memory over public observation fields only.

The fixed candidate generator and planner use no game names, source, metadata,
models, or answers. Each Decision represents one issued action. Call observe
after execution, or pass its resulting observation to the next decide/is_done
call. The two ingestion paths are equivalent and must not be mixed across agents.
"""

from collections import Counter, deque
from dataclasses import dataclass, field
import hashlib
import json
import random
from typing import Any

from arcengine import GameAction, GameState

from policy import Decision


MAX_STATES = 500
MAX_EDGES = 500
MAX_CANDIDATES = 64
MAX_PLAN_DEPTH = 2
MAX_PLAN_EDGES = 64
Command = tuple[int, int, int]


def final_image(observation: Any) -> tuple[tuple[int, ...], ...]:
    """Return the final rendered image, copying at most 64 by 64 pixels.

    Frames within one response are an animation sequence, not image layers.
    Empty images are accepted for terminal observations.
    """
    sequence = observation.frame
    if len(sequence) == 0:
        return ()
    image = sequence[-1]
    height = len(image)
    if height > 64:
        raise ValueError("observation image exceeds 64 rows")
    width = len(image[0]) if height else 0
    if width > 64 or any(len(row) != width for row in image):
        raise ValueError("observation image must be rectangular and at most 64 columns")
    result = tuple(tuple(int(pixel) for pixel in row) for row in image)
    if any(not 0 <= pixel <= 15 for row in result for pixel in row):
        raise ValueError("observation pixels must use the public 0..15 palette")
    return result


def _state_name(observation: Any) -> str:
    value = observation.state
    return value.name if hasattr(value, "name") else GameState(value).name


def _legal_actions(observation: Any) -> tuple[int, ...]:
    valid = {action.value for action in GameAction if action != GameAction.RESET}
    return tuple(sorted({int(action) for action in observation.available_actions} & valid))


def state_hash(observation: Any) -> str:
    """Hash final pixels, completion count, state and the legal-action set."""
    payload = [
        _state_name(observation), int(observation.levels_completed),
        _legal_actions(observation), final_image(observation),
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _command(decision: Decision) -> Command:
    action_id = decision.action_id
    if type(action_id) is not int or action_id not in range(8):
        raise ValueError("decision has an unsupported action id")
    if action_id == 6:
        if set(decision.data) != {"x", "y"}:
            raise ValueError("click decisions require exactly x and y")
        x, y = decision.data["x"], decision.data["y"]
        if any(type(value) is not int or not 0 <= value <= 63 for value in (x, y)):
            raise ValueError("click coordinates must be integers in 0..63")
        return action_id, x, y
    if decision.data:
        raise ValueError("simple decisions must have empty data")
    return action_id, -1, -1


@dataclass(frozen=True)
class _Snapshot:
    key: str
    image: tuple[tuple[int, ...], ...]
    levels: int
    state: str
    legal: tuple[int, ...]


def _snapshot(observation: Any) -> _Snapshot:
    image = final_image(observation)
    levels, state, legal = int(observation.levels_completed), _state_name(observation), _legal_actions(observation)
    payload = [state, levels, legal, image]
    key = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return _Snapshot(key, image, levels, state, legal)


def _component_points(image: tuple[tuple[int, ...], ...]) -> list[tuple[int, int]]:
    """Find at most 16 representatives with a single bounded pixel flood fill."""
    if not image or not image[0]:
        return []
    height, width = len(image), len(image[0])
    colors = Counter(pixel for row in image for pixel in row)
    background = min(colors, key=lambda color: (-colors[color], color))
    seen: set[tuple[int, int]] = set()
    components = []
    for y in range(height):
        for x in range(width):
            if image[y][x] == background or (x, y) in seen:
                continue
            color, stack, pixels = image[y][x], [(x, y)], []
            seen.add((x, y))
            while stack:
                px, py = stack.pop()
                pixels.append((px, py))
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen and image[ny][nx] == color:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            size = len(pixels)
            sx, sy = sum(px for px, _ in pixels), sum(py for _, py in pixels)
            representative = min(pixels, key=lambda point: ((point[0] * size - sx) ** 2 + (point[1] * size - sy) ** 2, point[1], point[0]))
            components.append((-size, y, x, color, representative))
    components.sort()
    return [component[-1] for component in components[:16]]


@dataclass
class _Record:
    attempts: int = 0
    observations: int = 0
    noops: int = 0
    deaths: int = 0
    progress: int = 0
    loops: int = 0


@dataclass
class _State:
    snapshot: _Snapshot
    candidates: tuple[Command, ...]
    records: dict[Command, _Record] = field(default_factory=dict)
    outgoing: list[tuple[str, Command, str]] = field(default_factory=list)
    visits: int = 0


@dataclass
class _Pending:
    before: _Snapshot
    decision: Decision
    command: Command


class ObservationReasoner:
    def __init__(self, seed: int = 0, max_actions: int = 500, mode: str = "frontier_plan"):
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        if type(max_actions) is not int or max_actions < 0:
            raise ValueError("max_actions must be a nonnegative integer")
        if mode not in {"candidate_uniform", "transition_memory", "frontier_plan"}:
            raise ValueError("unsupported reasoning mode")
        self.seed, self.max_actions, self.mode = seed, max_actions, mode
        self.action_counter = 0
        self._rng = random.Random(seed)
        self._states: dict[str, _State] = {}
        self._edges: dict[tuple[str, Command, str], int] = {}
        self._pending: _Pending | None = None
        self._last_consumed: tuple[Decision, str, str] | None = None
        self._counts: Counter[str] = Counter()
        self._last_edges_inspected = 0
        self._max_edges_inspected = 0

    def _candidates(self, snapshot: _Snapshot) -> tuple[Command, ...]:
        if snapshot.state in {"NOT_PLAYED", "GAME_OVER"}:
            return ((0, -1, -1),)
        if snapshot.state == "WIN":
            return ()
        commands = [(action, -1, -1) for action in snapshot.legal if action != 6]
        if 6 in snapshot.legal:
            points = [(x, y) for y in (8, 24, 40, 56) for x in (8, 24, 40, 56)]
            points.extend(_component_points(snapshot.image))
            seed_bytes = hashlib.sha256(f"{self.seed}:{snapshot.key}".encode()).digest()
            pixel_rng = random.Random(int.from_bytes(seed_bytes[:16], "big"))
            points.extend((pixel_rng.randrange(64), pixel_rng.randrange(64)) for _ in range(16))
            commands.extend((6, x, y) for x, y in sorted(set(points)))
        return tuple(sorted(set(commands)))[:MAX_CANDIDATES]

    def _get_state(self, snapshot: _Snapshot) -> _State:
        if snapshot.key in self._states:
            return self._states[snapshot.key]
        state = _State(snapshot, self._candidates(snapshot))
        if len(self._states) < MAX_STATES:
            self._states[snapshot.key] = state
        else:
            self._counts["state_capacity_skips"] += 1
        return state

    @staticmethod
    def _record_for(state: _State, command: Command) -> _Record | None:
        # External observations outside the frozen pool cannot grow per-state maps.
        if command not in state.candidates:
            return None
        return state.records.setdefault(command, _Record())

    def _learn(self, before: _Snapshot, command: Command, after: _Snapshot, count_attempt: bool) -> None:
        source, target = self._get_state(before), self._get_state(after)
        source.visits = max(source.visits, 1)
        loop = target.visits > 0
        target.visits += 1
        noop = before.key == after.key
        death = after.state == "GAME_OVER" and command[0] != 0
        progress = after.levels > before.levels or (after.state == "WIN" and before.state != "WIN")
        self._counts.update(observed_transitions=1, noops=int(noop), deaths=int(death), progress_events=int(progress))
        record = self._record_for(source, command)
        if record is not None:
            record.attempts += int(count_attempt)
            record.observations += 1
            record.noops += int(noop)
            record.deaths += int(death)
            record.progress += int(progress)
            record.loops += int(loop)
        edge = (before.key, command, after.key)
        if before.key not in self._states or after.key not in self._states:
            return
        if edge in self._edges:
            self._edges[edge] += 1
        elif len(self._edges) < MAX_EDGES:
            self._edges[edge] = 1
            source.outgoing.append(edge)
        else:
            self._counts["edge_capacity_skips"] += 1

    def _ingest_pending(self, observation: Any) -> None:
        if self._pending is None:
            return
        pending, after = self._pending, _snapshot(observation)
        self._learn(pending.before, pending.command, after, count_attempt=False)
        self._last_consumed = (pending.decision, pending.before.key, after.key)
        self._pending = None

    def observe(self, before: Any, decision: Decision, after: Any) -> None:
        """Record one executed action; repeated ingestion of that Decision is a no-op."""
        source, destination, command = _snapshot(before), _snapshot(after), _command(decision)
        if self._last_consumed is not None:
            last_decision, last_before, last_after = self._last_consumed
            if decision is last_decision and source.key == last_before and destination.key == last_after:
                return
        if self._pending is not None:
            if decision is not self._pending.decision or self._pending.before.key != source.key or self._pending.command != command:
                raise ValueError("observation does not match the pending action")
            self._learn(self._pending.before, command, destination, count_attempt=False)
            self._pending = None
        else:
            self._learn(source, command, destination, count_attempt=True)
        self._last_consumed = (decision, source.key, destination.key)

    def is_done(self, frames: list[Any], latest_frame: Any) -> bool:
        self._ingest_pending(latest_frame)
        return self.action_counter >= self.max_actions or _state_name(latest_frame) == "WIN"

    def _balanced_choice(self, commands: list[Command], state: _State, uniform: bool = False) -> Command:
        groups: dict[int, list[Command]] = {}
        for command in commands:
            groups.setdefault(command[0], []).append(command)
        types = sorted(groups)
        if not uniform:
            usage = {action: sum(record.attempts for command, record in state.records.items() if command[0] == action) for action in types}
            minimum = min(usage.values())
            types = [action for action in types if usage[action] == minimum]
        action = self._rng.choice(types)
        candidates = sorted(groups[action])
        if not uniform:
            minimum = min(state.records.get(command, _Record()).attempts for command in candidates)
            candidates = [command for command in candidates if state.records.get(command, _Record()).attempts == minimum]
        return self._rng.choice(candidates)

    @staticmethod
    def _untested(state: _State) -> list[Command]:
        return [command for command in state.candidates if not state.records.get(command, _Record()).attempts]

    def _plan(self, start: _State) -> list[Command]:
        queue = deque([(start.snapshot.key, None, 0)])
        seen = {start.snapshot.key}
        found: list[tuple[tuple[int, int], Command]] = []
        inspected = 0
        while queue and inspected < MAX_PLAN_EDGES:
            key, first, depth = queue.popleft()
            state = self._states[key]
            for edge in state.outgoing:
                if inspected >= MAX_PLAN_EDGES:
                    break
                inspected += 1  # Discarded and uncertain edges also consume the budget.
                _, command, destination = edge
                target = self._states[destination]
                record = state.records.get(command)
                if command[0] == 0 or command not in state.candidates or record is None:
                    continue
                if self._edges[edge] != record.observations:
                    continue  # Plan only through a command's observed single outcome.
                if target.snapshot.state in {"GAME_OVER", "WIN", "NOT_PLAYED"} or destination == key:
                    continue
                first_command = command if first is None else first
                if first_command not in start.candidates:
                    continue
                next_depth = depth + 1
                if self._untested(target):
                    found.append(((next_depth, target.visits), first_command))
                if next_depth < MAX_PLAN_DEPTH and destination not in seen:
                    seen.add(destination)
                    queue.append((destination, first_command, next_depth))
        self._last_edges_inspected = inspected
        self._max_edges_inspected = max(self._max_edges_inspected, inspected)
        if not found:
            return []
        rank = min(item[0] for item in found)
        return sorted({command for priority, command in found if priority == rank})

    def decide(self, latest_frame: Any) -> Decision:
        self._ingest_pending(latest_frame)
        if self.action_counter >= self.max_actions or _state_name(latest_frame) == "WIN":
            raise StopIteration("agent is complete or its action budget is exhausted")
        snapshot = _snapshot(latest_frame)
        state = self._get_state(snapshot)
        state.visits = max(state.visits, 1)
        self._last_edges_inspected = 0
        if not state.candidates:
            raise ValueError("no supported legal action advertised by environment")
        if snapshot.state in {"NOT_PLAYED", "GAME_OVER"}:
            command, reason = state.candidates[0], "observed state requires reset"
        elif self.mode == "candidate_uniform":
            command, reason = self._balanced_choice(list(state.candidates), state, uniform=True), "uniform action type then command"
        else:
            untested = self._untested(state)
            planned = self._plan(state) if self.mode == "frontier_plan" and not untested else []
            if untested:
                command, reason = self._balanced_choice(untested, state), "untested full command"
            elif planned:
                command, reason = self._balanced_choice(planned, state), "known route to untested commands"
                self._counts["plans_selected"] += 1
            else:
                def risk(candidate: Command) -> tuple[float, float, float, float]:
                    record = state.records.get(candidate, _Record())
                    denominator = max(record.observations, 1)
                    return (record.deaths / denominator, -record.progress / denominator, record.noops / denominator, record.loops / denominator)
                best = min(risk(candidate) for candidate in state.candidates)
                choices = [candidate for candidate in state.candidates if risk(candidate) == best]
                command, reason = self._balanced_choice(choices, state), "observed progress and loop risk"
        record = self._record_for(state, command)
        if record is not None:
            record.attempts += 1
        self.action_counter += 1
        data = {"x": command[1], "y": command[2]} if command[0] == 6 else {}
        decision = Decision(command[0], data, reason)
        self._pending = _Pending(snapshot, decision, command)
        return decision

    def choose_action(self, frames: list[Any], latest_frame: Any) -> GameAction:
        decision = self.decide(latest_frame)
        action = GameAction.from_id(decision.action_id)
        if decision.data:
            action.set_data(decision.data)
        action.reasoning = {"policy": self.mode, "reason": decision.reason, "seed": self.seed}
        return action

    def stats(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "actions": self.action_counter,
            "observed_transitions": self._counts["observed_transitions"],
            "states": len(self._states), "edges": len(self._edges),
            "noops": self._counts["noops"], "deaths": self._counts["deaths"],
            "progress_events": self._counts["progress_events"],
            "plans_selected": self._counts["plans_selected"],
            "last_edges_inspected": self._last_edges_inspected,
            "max_edges_inspected": self._max_edges_inspected,
            "state_capacity_skips": self._counts["state_capacity_skips"],
            "edge_capacity_skips": self._counts["edge_capacity_skips"],
            "pending": self._pending is not None,
        }
