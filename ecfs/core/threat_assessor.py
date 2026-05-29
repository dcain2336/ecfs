"""Threat assessment module for ECFS — evaluates system risk level."""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class ThreatLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ThreatReport:
    """Report of assessed threats and recommended actions."""
    level: ThreatLevel
    threats: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    timestamp: float = field(default_factory=time.time)


class ThreatAssessor:
    """Threat assessment engine for ECFS.

    Evaluates system state including transport availability,
    operational mode, packet loss, and traffic patterns to
    produce a threat level assessment.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, dict[str, float]] = {}
        self._last_assessment: Optional[ThreatReport] = None

    def update_metrics(self, plugin_name: str, metric: str, value: float) -> None:
        """Update a metric for a specific plugin.

        Metrics include: 'packet_loss_rate', 'latency_ms', 'error_count', etc.
        """
        if plugin_name not in self._metrics:
            self._metrics[plugin_name] = {}
        self._metrics[plugin_name][metric] = value

    def get_risk_score(self) -> float:
        """Calculate overall risk score from 0.0 (safe) to 1.0 (critical).

        Aggregates metrics from all plugins and returns a weighted risk score.
        """
        if not self._metrics:
            return 0.0

        total_risk = 0.0
        count = 0

        for plugin_name, metrics in self._metrics.items():
            plugin_risk = 0.0

            # Packet loss contributes directly to risk
            if "packet_loss_rate" in metrics:
                plugin_risk += min(metrics["packet_loss_rate"], 1.0) * 0.4

            # Error count contributes proportionally
            if "error_count" in metrics:
                errors = metrics["error_count"]
                plugin_risk += min(errors / 10.0, 1.0) * 0.3

            # High latency indicates issues
            if "latency_ms" in metrics:
                latency = metrics["latency_ms"]
                plugin_risk += min(latency / 1000.0, 1.0) * 0.2

            # Unusual traffic patterns
            if "unusual_traffic" in metrics:
                plugin_risk += min(metrics["unusual_traffic"], 1.0) * 0.1

            total_risk += plugin_risk
            count += 1

        # Normalize by number of plugins
        return min(total_risk / max(count, 1), 1.0)

    def _get_plugin_status(self, plugin) -> Optional[str]:
        """Get plugin status name (sync-safe).

        Uses _status attribute directly since get_status() is async.
        """
        # Try to get _status attribute directly (sync access)
        status = getattr(plugin, "_status", None)
        if status is not None and hasattr(status, "name"):
            return status.name
        # Fallback: check if plugin has a name attribute that's a status-like value
        status = getattr(plugin, "status", None)
        if status is not None and hasattr(status, "name"):
            return status.name
        return None

    def assess(
        self,
        plugins: list = None,
        state: Any = None,
        environment: dict = None,
    ) -> ThreatReport:
        """Assess current threat level.

        Args:
            plugins: List of transport plugins to evaluate.
            state: Current state machine state (optional).
            environment: Environmental factors (optional).

        Returns:
            ThreatReport with level, threats, and recommended actions.
        """
        threats = []
        recommended_actions = []
        risk_score = self.get_risk_score()

        # Check transport availability
        offline_count = 0
        total_count = 0
        if plugins:
            total_count = len(plugins)
            for plugin in plugins:
                try:
                    status_name = self._get_plugin_status(plugin)
                    if status_name == "OFFLINE":
                        offline_count += 1
                        threats.append(f"Plugin '{getattr(plugin, 'name', 'unknown')}' is offline")
                except Exception:
                    offline_count += 1
                    threats.append(f"Plugin '{getattr(plugin, 'name', 'unknown')}' status check failed")

            if offline_count > 0 and total_count > 0:
                offline_ratio = offline_count / total_count
                risk_score += offline_ratio * 0.5
                if offline_ratio > 0.5:
                    threats.append(f"Majority of transports offline ({offline_count}/{total_count})")
                    recommended_actions.append("Activate backup transports")

        # Check state
        state_name = None
        if state is not None:
            state_name = getattr(state, "name", str(state))
            if state_name == "EMERGENCY":
                threats.append("System in EMERGENCY state")
                recommended_actions.append("Escalate to manual intervention")
                risk_score += 0.3
            elif state_name == "DEGRADED":
                threats.append("System in DEGRADED state")
                recommended_actions.append("Monitor transport recovery")
                risk_score += 0.15

        # Check environment factors
        if environment:
            if environment.get("jamming_detected", False):
                threats.append("Signal jamming detected")
                recommended_actions.append("Switch to alternative transports")
                risk_score += 0.4

            if environment.get("interception_suspected", False):
                threats.append("Traffic interception suspected")
                recommended_actions.append("Enable end-to-end encryption verification")
                risk_score += 0.5

        # Determine threat level from risk score
        risk_score = min(risk_score, 1.0)
        if risk_score >= 0.8:
            level = ThreatLevel.CRITICAL
        elif risk_score >= 0.5:
            level = ThreatLevel.HIGH
        elif risk_score >= 0.2:
            level = ThreatLevel.MEDIUM
        else:
            level = ThreatLevel.LOW

        # Add default recommendations based on level
        if level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL):
            recommended_actions.append("Alert system operator")
            recommended_actions.append("Log all transport activity")
        if level == ThreatLevel.CRITICAL:
            recommended_actions.append("Consider emergency shutdown")

        report = ThreatReport(
            level=level,
            threats=threats,
            recommended_actions=recommended_actions,
            risk_score=risk_score,
        )
        self._last_assessment = report
        return report
