"""Integration tests for ECFS Phase 4."""

import asyncio
import os
import pytest
from ecfs.plugins.ultrasonic_transport import UltrasonicAudioTransport, MockAudio
from ecfs.plugins.stego_transport import SteganographicHTTP
from ecfs.core.state_machine import StateMachine, State
from ecfs.core.threat_assessor import ThreatAssessor, ThreatLevel


def test_ultrasonic_signal_roundtrip():
    """Test encode -> signal -> decode produces original data."""
    audio = MockAudio()
    transport = UltrasonicAudioTransport(audio=audio)

    test_data = b"Phase 4 ultrasonic test data"
    signal = transport.encode_to_signal(test_data)
    decoded = transport.decode_from_signal(signal)

    assert decoded == test_data


def test_steganography_statistical():
    """Test that chi-squared of encrypted data is < 0.1."""
    stego = SteganographicHTTP()

    # Generate random-looking encrypted data
    encrypted_data = os.urandom(4096)
    chi_sq = stego.calculate_chi_squared(encrypted_data)

    assert chi_sq < 0.1


def test_failover_state_with_threats():
    """Test threat assessor + state machine integration."""
    sm = StateMachine()
    assessor = ThreatAssessor()

    # Start in normal state
    assert sm.current_state == State.NORMAL

    # Simulate degrading conditions
    sm.transition(State.DEGRADED)
    report = assessor.assess(plugins=[], state=sm.current_state)
    assert report.level in (ThreatLevel.LOW, ThreatLevel.MEDIUM, ThreatLevel.HIGH)

    # Transition to emergency
    sm.transition(State.EMERGENCY)
    report = assessor.assess(plugins=[], state=sm.current_state)
    assert report.level in (ThreatLevel.MEDIUM, ThreatLevel.HIGH, ThreatLevel.CRITICAL)

    # Verify state history
    assert len(sm.state_history) == 2

    # Reset
    sm.reset()
    assert sm.current_state == State.NORMAL
