"""Optional bounded telemetry overlay for System-1.

This is a deterministic control/diagnostic model, not a claim of biological
cognition. It does not independently change runtime policy. Adjustments are
explicit inputs and snapshots are suitable for S7/S12 review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


@dataclass
class NeuralFieldChannel:
    from_system: str
    gain: float
    activation: float
    equilibrium: float


@dataclass
class NeuralFieldState:
    potential: float = 0.50
    resting_potential: float = 0.45
    capacitance: float = 1.0
    leak: float = 0.05
    channels: list[NeuralFieldChannel] = field(default_factory=list)


class System1NeuralOverlay:
    """Bounded diagnostic overlay with a no-side-effect update API."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        data = dict(config or {})
        self.state = NeuralFieldState(
            potential=clamp(float(data.get("potential_init", 0.50))),
            resting_potential=clamp(float(data.get("resting_potential", 0.45))),
            capacitance=max(0.01, float(data.get("capacitance", 1.0))),
            leak=clamp(float(data.get("leak", 0.05))),
        )
        defaults = (
            {"from_system": "S2", "gain": 0.60, "activation": 0.50, "equilibrium": 0.70},
            {"from_system": "S3", "gain": 0.40, "activation": 0.50, "equilibrium": 0.60},
            {"from_system": "S4", "gain": 0.30, "activation": 0.30, "equilibrium": 0.70},
        )
        for channel in data.get("channels", defaults):
            self.state.channels.append(NeuralFieldChannel(str(channel["from_system"]), clamp(float(channel["gain"])), clamp(float(channel["activation"])), clamp(float(channel["equilibrium"]))))
        self.emergence_threshold = clamp(float(data.get("emergence_threshold", 0.80)))

    def update(self, *, kpi_signals: Mapping[str, Any], uncertainty: Mapping[str, Any], dt: float = 0.05) -> dict[str, Any]:
        dt = max(0.0, min(float(dt), 1.0))
        completeness = clamp(float(kpi_signals.get("completeness_contribution", 0.0)))
        trajectory = clamp(float(kpi_signals.get("trajectory_fit_contribution", 0.0)) * 5.0)
        uncertainty_score = clamp(float(uncertainty.get("score", 1.0)))
        channel_current = sum(channel.gain * channel.activation * (channel.equilibrium - self.state.potential) for channel in self.state.channels)
        kpi_drive = 0.12 * completeness + 0.08 * trajectory - 0.10 * uncertainty_score
        leak_current = self.state.leak * (self.state.resting_potential - self.state.potential)
        delta = dt * (channel_current + kpi_drive + leak_current) / self.state.capacitance
        self.state.potential = clamp(self.state.potential + delta)
        return self.snapshot(kpi_signals=kpi_signals, uncertainty=uncertainty, delta=delta)

    def apply_field_adjustment(self, adjustment: Mapping[str, Any]) -> None:
        for item in adjustment.get("channel_scales", ()):
            source = str(item.get("from_system", ""))
            scale = max(0.0, float(item.get("scale", 1.0)))
            for channel in self.state.channels:
                if channel.from_system == source:
                    channel.gain = clamp(channel.gain * scale)
        if "leak_delta" in adjustment:
            self.state.leak = clamp(self.state.leak + float(adjustment["leak_delta"]))
        if "emergence_threshold" in adjustment:
            self.emergence_threshold = clamp(float(adjustment["emergence_threshold"]))

    def snapshot(self, *, kpi_signals: Mapping[str, Any], uncertainty: Mapping[str, Any], delta: float = 0.0) -> dict[str, Any]:
        return {
            "model": "bounded_neurodynamic_telemetry",
            "potential": round(self.state.potential, 6),
            "resting_potential": self.state.resting_potential,
            "leak": self.state.leak,
            "delta": round(delta, 6),
            "emergence_threshold": self.emergence_threshold,
            "emergence_signal": self.state.potential >= self.emergence_threshold,
            "channels": [{"from_system": item.from_system, "gain": item.gain, "activation": item.activation, "equilibrium": item.equilibrium} for item in self.state.channels],
            "inputs": {"completeness": kpi_signals.get("completeness_contribution"), "trajectory": kpi_signals.get("trajectory_fit_contribution"), "uncertainty": uncertainty.get("score")},
        }
