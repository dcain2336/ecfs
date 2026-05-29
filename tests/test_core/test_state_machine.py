"""Tests for failover state machine."""

import pytest
from ecfs.core.state_machine import StateMachine, State
from ecfs.plugins.base import TransportStatus


@pytest.fixture
def sm():
    return StateMachine()


def test_initial_state_normal(sm):
    """State machine starts in NORMAL state."""
    assert sm.current_state == State.NORMAL


def test_degraded_transition(sm):
    """Test transition from NORMAL to DEGRADED."""
    sm.transition(State.DEGRADED)
    assert sm.current_state == State.DEGRADED


def test_emergency_transition(sm):
    """Test transition from DEGRADED to EMERGENCY."""
    sm.transition(State.DEGRADED)
    sm.transition(State.EMERGENCY)
    assert sm.current_state == State.EMERGENCY


def test_recovery_transition(sm):
    """Test transition from EMERGENCY to RECOVERY to NORMAL."""
    sm.transition(State.EMERGENCY)
    sm.transition(State.RECOVERY)
    assert sm.current_state == State.RECOVERY
    sm.transition(State.NORMAL)
    assert sm.current_state == State.NORMAL


def test_manual_reset(sm):
    """Test manual reset from any state to NORMAL."""
    sm.transition(State.EMERGENCY)
    sm.reset()
    assert sm.current_state == State.NORMAL


def test_state_history_tracking(sm):
    """Test that state history records all transitions."""
    sm.transition(State.DEGRADED)
    sm.transition(State.EMERGENCY)
    sm.transition(State.RECOVERY)
    sm.transition(State.NORMAL)

    history = sm.state_history
    assert len(history) == 4
    assert history[0][1] == State.NORMAL
    assert history[0][2] == State.DEGRADED
    assert history[1][1] == State.DEGRADED
    assert history[1][2] == State.EMERGENCY
    assert history[2][1] == State.EMERGENCY
    assert history[2][2] == State.RECOVERY
    assert history[3][1] == State.RECOVERY
    assert history[3][2] == State.NORMAL


def test_callbacks(sm):
    """Test on_enter and on_exit callbacks."""
    enter_called = []
    exit_called = []

    sm.on_enter(State.DEGRADED, lambda old, new: enter_called.append(new))
    sm.on_exit(State.NORMAL, lambda old, new: exit_called.append(old))

    sm.transition(State.DEGRADED)

    assert enter_called == [State.DEGRADED]
    assert exit_called == [State.NORMAL]


def test_all_online_stays_normal(sm):
    """Test that with all transports online, state stays NORMAL."""
    from unittest.mock import MagicMock

    plugins = []
    for i in range(4):
        p = MagicMock()
        p._status = TransportStatus.ONLINE
        p.transport_type = MagicMock(value="internet")
        plugins.append(p)

    result = sm.evaluate(plugins)
    assert result == State.NORMAL
