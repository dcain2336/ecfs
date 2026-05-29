"""Failover state machine for ECFS — manages transport availability states."""

import time
from enum import Enum, auto
from typing import Callable, Optional


class State(Enum):
    NORMAL = auto()
    DEGRADED = auto()
    EMERGENCY = auto()
    RECOVERY = auto()


class StateMachine:
    """Failover state machine for ECFS.

    Manages transitions between operational states based on
    transport availability. Supports callbacks for state entry/exit
    and maintains a full history of transitions.
    """

    def __init__(self) -> None:
        self._state: State = State.NORMAL
        self._on_enter: dict[State, list[Callable]] = {s: [] for s in State}
        self._on_exit: dict[State, list[Callable]] = {s: [] for s in State}
        self._state_history: list[tuple[float, State, State]] = []

    @property
    def current_state(self) -> State:
        return self._state

    @property
    def state_history(self) -> list[tuple[float, State, State]]:
        return list(self._state_history)

    def on_enter(self, state: State, callback: Callable) -> None:
        """Register a callback to run when entering a state."""
        self._on_enter[state].append(callback)

    def on_exit(self, state: State, callback: Callable) -> None:
        """Register a callback to run when exiting a state."""
        self._on_exit[state].append(callback)

    def transition(self, new_state: State) -> None:
        """Transition to a new state, firing callbacks."""
        old_state = self._state
        if old_state == new_state:
            return

        # Fire exit callbacks
        for callback in self._on_exit.get(old_state, []):
            callback(old_state, new_state)

        # Record transition
        timestamp = time.time()
        self._state_history.append((timestamp, old_state, new_state))

        # Update state
        self._state = new_state

        # Fire enter callbacks
        for callback in self._on_enter.get(new_state, []):
            callback(old_state, new_state)

    def evaluate(self, available_plugins: list) -> State:
        """Evaluate current transport availability and transition if needed.

        Uses the _status attribute directly (sync access) since
        get_status() is async and evaluate() is sync.

        Args:
            available_plugins: List of transport plugin instances.
                Each should have a _status attribute with a TransportStatus value.

        Returns:
            The resulting state after evaluation.
        """
        if not available_plugins:
            self.transition(State.EMERGENCY)
            return self._state

        # Count online vs total
        total = len(available_plugins)
        online = 0
        radio_only = True

        for plugin in available_plugins:
            try:
                # Use _status attribute directly (sync access) since
                # get_status() is async and evaluate() is sync.
                status = getattr(plugin, "_status", None)
                if hasattr(status, "value"):
                    from ecfs.plugins.base import TransportStatus

                    if status in (
                        TransportStatus.ONLINE,
                        TransportStatus.DEGRADED,
                    ):
                        online += 1
                        # Check if it's a radio-only transport
                        plugin_type = getattr(plugin, "transport_type", None)
                        if plugin_type is not None:
                            from ecfs.plugins.base import TransportType

                            if plugin_type != TransportType.RADIO:
                                radio_only = False
            except Exception:
                pass

        ratio = online / total if total > 0 else 0.0

        if self._state == State.RECOVERY:
            if ratio >= 0.75:
                self.transition(State.NORMAL)
            return self._state

        if self._state == State.EMERGENCY:
            if online > 0 and not radio_only:
                self.transition(State.RECOVERY)
            return self._state

        if self._state == State.DEGRADED:
            if ratio < 0.25 or (radio_only and online > 0):
                self.transition(State.EMERGENCY)
            elif ratio >= 0.75:
                self.transition(State.NORMAL)
            return self._state

        # NORMAL state
        if ratio < 0.25:
            self.transition(State.EMERGENCY)
        elif ratio < 0.50:
            self.transition(State.DEGRADED)

        return self._state

    def reset(self) -> None:
        """Manually reset to NORMAL state from any state."""
        self.transition(State.NORMAL)
