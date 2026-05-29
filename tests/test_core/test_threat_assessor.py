"""Tests for threat assessment module."""

import pytest
from ecfs.core.threat_assessor import ThreatAssessor, ThreatLevel, ThreatReport
from ecfs.core.state_machine import State
from ecfs.plugins.base import TransportStatus


@pytest.fixture
def assessor():
    return ThreatAssessor()


def test_low_threat_all_online(assessor):
    """Test LOW threat when all transports are online."""
    from unittest.mock import MagicMock

    plugins = []
    for i in range(3):
        p = MagicMock()
        p.name = f"plugin_{i}"
        p._status = TransportStatus.ONLINE
        plugins.append(p)

    report = assessor.assess(plugins=plugins, state=State.NORMAL)
    assert report.level == ThreatLevel.LOW
    assert report.risk_score < 0.3


def test_high_threat_most_offline(assessor):
    """Test HIGH threat when most transports are offline."""
    from unittest.mock import MagicMock

    plugins = []
    for i in range(4):
        p = MagicMock()
        p.name = f"plugin_{i}"
        if i < 3:
            p._status = TransportStatus.OFFLINE
        else:
            p._status = TransportStatus.ONLINE
        plugins.append(p)

    report = assessor.assess(plugins=plugins, state=State.DEGRADED)
    assert report.level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL)


def test_critical_emergency_state(assessor):
    """Test CRITICAL threat in emergency state with offline transports."""
    from unittest.mock import MagicMock

    plugins = []
    for i in range(4):
        p = MagicMock()
        p.name = f"plugin_{i}"
        p._status = TransportStatus.OFFLINE
        plugins.append(p)

    report = assessor.assess(plugins=plugins, state=State.EMERGENCY)
    assert report.level == ThreatLevel.CRITICAL


def test_risk_score_range(assessor):
    """Test that risk score is always between 0.0 and 1.0."""
    # Test with various metrics
    assessor.update_metrics("plugin1", "packet_loss_rate", 0.5)
    assessor.update_metrics("plugin1", "error_count", 5)
    score = assessor.get_risk_score()
    assert 0.0 <= score <= 1.0


def test_recommended_actions(assessor):
    """Test that threat reports include recommended actions."""
    from unittest.mock import MagicMock

    plugins = []
    p = MagicMock()
    p.name = "plugin_0"
    p._status = TransportStatus.OFFLINE
    plugins.append(p)

    report = assessor.assess(
        plugins=plugins,
        state=State.EMERGENCY,
        environment={"jamming_detected": True},
    )
    assert len(report.recommended_actions) > 0


def test_update_metrics(assessor):
    """Test updating metrics for plugins."""
    assessor.update_metrics("lora", "packet_loss_rate", 0.1)
    assessor.update_metrics("lora", "latency_ms", 150.0)

    score = assessor.get_risk_score()
    assert 0.0 <= score <= 1.0
    assert score > 0.0  # Should have some risk due to metrics
