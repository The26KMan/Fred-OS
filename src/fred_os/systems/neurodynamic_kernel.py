"""Shared explicit-state neurodynamic control kernel for System-OS.

This module implements an engineering control abstraction inspired by
conductance/gating models.  It does not claim biological fidelity.  The
transition is pure: serialized FieldState(t) plus typed inputs produces
FieldState(t+1), a control decision, and a reproducible receipt.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Any, Mapping, Sequence


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("non-finite controller value")
    return max(low, min(high, value))


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + sha256(encoded).hexdigest()


class ChannelClass(str, Enum):
    EXPLORATORY = "exploratory"
    HOMEOSTATIC = "homeostatic"
    INHIBITORY = "inhibitory"
    MODULATORY = "modulatory"


@dataclass(frozen=True)
class GlobalParametersSnapshot:
    revision: str
    content_digest: str
    values: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.revision or not self.content_digest.startswith("sha256:"):
            raise ValueError("Global Parameters require revision and sha256 digest")


@dataclass(frozen=True)
class ChannelState:
    channel_id: str
    source_system: str
    role: str
    channel_class: ChannelClass
    conductance: float
    gate: float
    equilibrium: float
    alpha_base: float = 0.4
    beta_base: float = 0.5

    def __post_init__(self) -> None:
        if not self.channel_id or not self.source_system or not self.role:
            raise ValueError("channel identity fields are required")
        for name in ("conductance", "gate", "equilibrium", "alpha_base", "beta_base"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0 or value > 1:
                raise ValueError(f"{name} must be within [0,1]")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ChannelState":
        source = str(raw.get("source_system", raw.get("from", "unknown")))
        role = str(raw.get("role", source.lower()))
        klass = raw.get("channel_class", "exploratory")
        return cls(
            channel_id=str(raw.get("channel_id", f"{source}:{role}")),
            source_system=source,
            role=role,
            channel_class=ChannelClass(klass),
            conductance=float(raw.get("conductance", raw.get("g", 0.0))),
            gate=float(raw.get("gate", raw.get("a", 0.0))),
            equilibrium=float(raw.get("equilibrium", raw.get("E", 0.5))),
            alpha_base=float(raw.get("alpha_base", 0.4)),
            beta_base=float(raw.get("beta_base", 0.5)),
        )


@dataclass(frozen=True)
class FieldProfile:
    system: str
    version: str
    controlled_faculty: str
    v_rest: float = 0.45
    capacitance: float = 1.0
    dt: float = 0.1
    leak: float = 0.08
    homeostasis_gain: float = 0.65
    ceiling_gain: float = 2.0
    floor_gain: float = 2.0
    soft_low: float = 0.18
    soft_high: float = 0.82
    target_base: float = 0.48
    target_drive_gain: float = 0.24
    target_overload_drop: float = 0.10
    target_restriction_drop: float = 0.08
    max_delta_v: float = 0.08
    hysteresis: float = 0.025
    minimum_region_dwell: int = 2
    external_weights: Mapping[str, float] = field(default_factory=dict)
    feedback_weights: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.system or not self.version or not self.controlled_faculty:
            raise ValueError("profile identity is required")
        if self.capacitance <= 0 or self.dt <= 0 or self.max_delta_v <= 0:
            raise ValueError("capacitance, dt, and max_delta_v must be positive")
        if not 0 <= self.soft_low < self.soft_high <= 1:
            raise ValueError("invalid soft operating interval")


@dataclass(frozen=True)
class FieldState:
    system: str
    profile_version: str
    step: int
    voltage: float
    channels: tuple[ChannelState, ...]
    operating_region: str = "stable"
    region_dwell: int = 0
    global_parameters_revision: str = "unspecified"
    global_parameters_digest: str = "sha256:" + "0" * 64
    prior_transition_digest: str | None = None

    def __post_init__(self) -> None:
        if self.step < 0 or not 0 <= self.voltage <= 1:
            raise ValueError("invalid field state")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "FieldState":
        return cls(
            system=str(raw["system"]),
            profile_version=str(raw["profile_version"]),
            step=int(raw.get("step", 0)),
            voltage=float(raw.get("voltage", raw.get("V", 0.45))),
            channels=tuple(ChannelState.from_dict(ch) for ch in raw.get("channels", [])),
            operating_region=str(raw.get("operating_region", "stable")),
            region_dwell=int(raw.get("region_dwell", 0)),
            global_parameters_revision=str(raw.get("global_parameters_revision", "unspecified")),
            global_parameters_digest=str(raw.get("global_parameters_digest", "sha256:" + "0" * 64)),
            prior_transition_digest=raw.get("prior_transition_digest"),
        )


@dataclass(frozen=True)
class CouplingSignal:
    signal_id: str
    source_system: str
    target_system: str
    signal_type: str
    value: float
    basis: tuple[str, ...] = ()
    authority: str = "operational"

    def __post_init__(self) -> None:
        if not self.signal_id or not self.source_system or not self.target_system:
            raise ValueError("signal identity is required")
        if not 0 <= self.value <= 1:
            raise ValueError("signal value must be within [0,1]")


def initial_state(profile: FieldProfile, channels: Sequence[ChannelState], params: GlobalParametersSnapshot) -> FieldState:
    return FieldState(
        system=profile.system,
        profile_version=profile.version,
        step=0,
        voltage=profile.v_rest,
        channels=tuple(channels),
        global_parameters_revision=params.revision,
        global_parameters_digest=params.content_digest,
    )


def _region(voltage: float) -> str:
    if voltage < 0.30:
        return "underactive"
    if voltage < 0.62:
        return "stable"
    if voltage < 0.76:
        return "exploratory"
    if voltage < 0.88:
        return "saturated"
    return "critical"


def _region_with_hysteresis(state: FieldState, voltage: float, profile: FieldProfile) -> tuple[str, int]:
    candidate = _region(voltage)
    if candidate == state.operating_region:
        return candidate, state.region_dwell + 1
    boundaries = {"underactive": 0.30, "stable": 0.62, "exploratory": 0.76, "saturated": 0.88}
    boundary = boundaries.get(min((state.operating_region, candidate), key=lambda x: list(boundaries).index(x) if x in boundaries else 4), 0.5)
    if state.region_dwell < profile.minimum_region_dwell or abs(voltage - boundary) < profile.hysteresis:
        return state.operating_region, state.region_dwell + 1
    return candidate, 1


def _normalized_load(load: Mapping[str, Any], key: str) -> float:
    return clamp(float(load.get(key, 0.0)))


def transition(
    state: FieldState,
    profile: FieldProfile,
    load: Mapping[str, Any],
    params: GlobalParametersSnapshot,
    signals: Sequence[CouplingSignal] = (),
) -> dict[str, Any]:
    """Advance one deterministic control step without mutating input state."""
    if state.system != profile.system or state.profile_version != profile.version:
        raise ValueError("state/profile identity mismatch")
    if state.global_parameters_digest != params.content_digest or state.global_parameters_revision != params.revision:
        raise ValueError("state/global-parameter snapshot mismatch")
    accepted_signals = [s for s in signals if s.target_system == state.system]
    signal_load: dict[str, float] = {}
    for signal in accepted_signals:
        signal_load[signal.signal_type] = max(signal_load.get(signal.signal_type, 0.0), signal.value)

    merged = dict(load)
    for key, value in signal_load.items():
        merged[key] = max(float(merged.get(key, 0.0)), value)
    overload = _normalized_load(merged, "overload")
    governance = _normalized_load(merged, "governance_restriction")
    recovery = _normalized_load(merged, "recovery_signal")
    redundancy = _normalized_load(merged, "redundancy")
    drive_keys = ("mapping_demand", "association_demand", "ambiguity", "novelty", "temporal_relevance")
    drive = max((_normalized_load(merged, key) for key in drive_keys), default=0.0)

    target = clamp(
        profile.target_base
        + profile.target_drive_gain * drive
        - profile.target_overload_drop * overload
        - profile.target_restriction_drop * governance,
        profile.soft_low,
        profile.soft_high,
    )
    channel_current = 0.0
    updated_channels: list[ChannelState] = []
    channel_telemetry: list[dict[str, Any]] = []
    for ch in state.channels:
        if ch.channel_class is ChannelClass.EXPLORATORY:
            demand = max(drive, _normalized_load(merged, ch.role))
            alpha = ch.alpha_base * demand * (1.0 - overload) * (1.0 - state.voltage)
            beta = ch.beta_base * clamp(overload + governance + redundancy) * (0.5 + state.voltage)
        elif ch.channel_class in {ChannelClass.HOMEOSTATIC, ChannelClass.INHIBITORY}:
            demand = max(overload, governance, recovery, abs(state.voltage - target))
            alpha = ch.alpha_base * demand * (0.5 + state.voltage)
            beta = ch.beta_base * (1.0 - demand) * (1.0 - state.voltage)
        else:
            demand = max(drive, recovery)
            alpha = ch.alpha_base * demand * (1.0 - state.voltage)
            beta = ch.beta_base * overload * (0.5 + state.voltage)
        next_gate = clamp(ch.gate + profile.dt * (alpha * (1.0 - ch.gate) - beta * ch.gate))
        current = ch.conductance * next_gate * (ch.equilibrium - state.voltage)
        channel_current += current
        updated = ChannelState(
            ch.channel_id, ch.source_system, ch.role, ch.channel_class,
            ch.conductance, next_gate, ch.equilibrium, ch.alpha_base, ch.beta_base,
        )
        updated_channels.append(updated)
        channel_telemetry.append({**asdict(updated), "channel_class": updated.channel_class.value,
                                  "alpha": alpha, "beta": beta, "current": current})

    i_external = sum(float(weight) * _normalized_load(merged, key) for key, weight in profile.external_weights.items())
    i_feedback = sum(float(weight) * _normalized_load(merged, key) for key, weight in profile.feedback_weights.items())
    i_homeostasis = profile.homeostasis_gain * (target - state.voltage)
    i_ceiling = -profile.ceiling_gain * max(0.0, state.voltage - profile.soft_high) ** 2
    i_floor = profile.floor_gain * max(0.0, profile.soft_low - state.voltage) ** 2
    i_leak = -profile.leak * (state.voltage - profile.v_rest)
    total = channel_current + i_external + i_feedback + i_homeostasis + i_ceiling + i_floor + i_leak
    raw_delta = profile.dt * total / profile.capacitance
    limited_delta = max(-profile.max_delta_v, min(profile.max_delta_v, raw_delta))
    unclamped = state.voltage + limited_delta
    next_voltage = clamp(unclamped)
    hard_clamp = not math.isclose(unclamped, next_voltage, abs_tol=1e-15)
    region, dwell = _region_with_hysteresis(state, next_voltage, profile)

    next_state_body = {
        "system": state.system,
        "profile_version": profile.version,
        "step": state.step + 1,
        "voltage": next_voltage,
        "channels": channel_telemetry,
        "operating_region": region,
        "region_dwell": dwell,
        "global_parameters_revision": params.revision,
        "global_parameters_digest": params.content_digest,
    }
    transition_digest = digest({
        "previous_state": asdict(state), "load": merged,
        "signals": [asdict(s) for s in accepted_signals], "next_state": next_state_body,
    })
    next_state = FieldState(
        system=state.system, profile_version=profile.version, step=state.step + 1,
        voltage=next_voltage, channels=tuple(updated_channels), operating_region=region,
        region_dwell=dwell, global_parameters_revision=params.revision,
        global_parameters_digest=params.content_digest, prior_transition_digest=transition_digest,
    )
    currents = {
        "I_channels": channel_current, "I_external": i_external,
        "I_feedback": i_feedback, "I_homeostasis": i_homeostasis,
        "I_ceiling": i_ceiling, "I_floor": i_floor, "I_leak": i_leak,
        "dV_dt": total / profile.capacitance, "raw_delta_v": raw_delta,
        "applied_delta_v": limited_delta,
    }
    return {
        "field_state": {**asdict(next_state), "channels": channel_telemetry},
        "previous_voltage": state.voltage,
        "target_voltage": target,
        "load_inputs": {k: float(v) for k, v in merged.items() if isinstance(v, (int, float))},
        "accepted_signals": [asdict(s) for s in accepted_signals],
        "currents": currents,
        "hard_clamp_applied": hard_clamp,
        "rate_limit_applied": not math.isclose(raw_delta, limited_delta, abs_tol=1e-15),
        "transition_digest": transition_digest,
        "model_semantics": {"kind": "HH-inspired control abstraction", "biological_fidelity_claimed": False},
    }


def stability_summary(voltages: Sequence[float], *, soft_low: float, soft_high: float) -> dict[str, Any]:
    if not voltages:
        raise ValueError("voltage history is required")
    tail = list(voltages[-min(25, len(voltages)):])
    variation = max(tail) - min(tail)
    clamp_count = sum(v <= 0.0 or v >= 1.0 for v in voltages)
    return {
        "steps": len(voltages), "minimum": min(voltages), "maximum": max(voltages),
        "final": voltages[-1], "late_window_variation": variation,
        "hard_boundary_samples": clamp_count,
        "within_soft_operating_range": soft_low <= voltages[-1] <= soft_high,
        "settled": variation < 0.002,
    }
