"""Deterministic TOML configuration loading for Fred-OS vNext."""
from __future__ import annotations

import copy
import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

class ConfigError(RuntimeError):
    pass

_MISSING = object()

def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _merge(dict(result[key]), value)
        else:
            result[key] = copy.deepcopy(value)
    return result

def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value

def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value

@dataclass(frozen=True)
class RuntimeConfig:
    _data: Mapping[str, Any]
    config_hash: str
    root_dir: Path

    def get(self, dotted_path: str, default: Any = _MISSING) -> Any:
        current: Any = self._data
        for part in dotted_path.split('.'):
            if not isinstance(current, Mapping) or part not in current:
                if default is _MISSING:
                    raise ConfigError(f"Missing required configuration key: {dotted_path}")
                return default
            current = current[part]
        return current

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._data)

    def resolve_path(self, dotted_path: str) -> Path:
        return self.root_dir / str(self.get(dotted_path))

class ConfigLoader:
    @classmethod
    def build(cls, *, root_dir: str | Path = '.', base_path: str = 'config/systemos_base.toml', profile: str | None = None) -> RuntimeConfig:
        root = Path(root_dir).resolve()
        path = root / base_path
        if not path.exists():
            raise ConfigError(f"Configuration not found: {path}")
        with path.open('rb') as handle:
            data = tomllib.load(handle)
        selected = profile or data.get('meta', {}).get('profile', 'production')
        overlay = path.parent / 'profiles' / f'{selected}.toml'
        if overlay.exists():
            with overlay.open('rb') as handle:
                data = _merge(data, tomllib.load(handle))
        data.setdefault('meta', {})['profile'] = selected
        canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
        config = RuntimeConfig(_freeze(data), hashlib.sha256(canonical.encode()).hexdigest()[:16], root)
        from .invariants import InvariantChecker
        InvariantChecker.check(config)
        return config
