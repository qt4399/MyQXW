from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from memory.memory_store import YAML_DIR, ensure_memory_layout

NEURON_CONFIG_PATH = Path(__file__).resolve().parent / "neurons.yaml"
NEURON_STATE_PATH = YAML_DIR / "neuron_state.yaml"


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _write_yaml(path, default)
        return dict(default)

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        _write_yaml(path, default)
        return dict(default)

    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        return dict(default)

    merged = dict(default)
    merged.update(loaded)
    return merged


def _default_neuron_config() -> dict[str, Any]:
    return {
        "version": 1,
        "poll_seconds": 1.0,
        "neurons": [
            {
                "id": "temp_overflow_pressure",
                "enabled": True,
                "target_service": "sleep",
                "runner": "temp_digest",
                "cooldown_seconds": 300,
                "decay": 0.94,
                "gain": 0.25,
                "base_probability": 0.0,
                "probability_gain": 0.18,
                "max_probability": 0.75,
                "max_accumulator": 3.0,
                "post_fire_accumulator": 0.2,
            },
            {
                "id": "day_closure_pressure",
                "enabled": True,
                "target_service": "sleep",
                "runner": "daily_summary",
                "cooldown_seconds": 1800,
                "decay": 0.97,
                "gain": 0.12,
                "base_probability": 0.0,
                "probability_gain": 0.12,
                "max_probability": 0.45,
                "max_accumulator": 2.0,
                "post_fire_accumulator": 0.15,
            },
            {
                "id": "subjective_pulse",
                "enabled": True,
                "target_service": "heart",
                "runner": "interrupt",
                "cooldown_seconds": 120,
                "decay": 0.95,
                "gain": 0.08,
                "base_probability": 0.01,
                "probability_gain": 0.08,
                "max_probability": 0.20,
                "max_accumulator": 1.5,
                "post_fire_accumulator": 0.05,
            },
        ],
    }


def _default_neuron_state() -> dict[str, Any]:
    return {
        "version": 1,
        "neurons": {},
    }


def _normalize_neuron_config_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    neuron_id = str(item.get("id", "")).strip()
    target_service = str(item.get("target_service", "")).strip()
    runner = str(item.get("runner", "")).strip()
    if not neuron_id or not target_service or not runner:
        return None

    return {
        "id": neuron_id,
        "enabled": bool(item.get("enabled", False)),
        "target_service": target_service,
        "runner": runner,
        "cooldown_seconds": max(1, int(item.get("cooldown_seconds", 60) or 60)),
        "decay": float(item.get("decay", 0.95) or 0.95),
        "gain": float(item.get("gain", 0.1) or 0.1),
        "base_probability": float(item.get("base_probability", 0.0) or 0.0),
        "probability_gain": float(item.get("probability_gain", 0.1) or 0.1),
        "max_probability": float(item.get("max_probability", 1.0) or 1.0),
        "max_accumulator": float(item.get("max_accumulator", 5.0) or 5.0),
        "post_fire_accumulator": float(item.get("post_fire_accumulator", 0.0) or 0.0),
    }


def _normalize_neuron_state_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}

    return {
        "accumulator": float(item.get("accumulator", 0.0) or 0.0),
        "last_evaluated_at": item.get("last_evaluated_at"),
        "last_fired_at": item.get("last_fired_at"),
        "last_signal": float(item.get("last_signal", 0.0) or 0.0),
        "last_probability": float(item.get("last_probability", 0.0) or 0.0),
        "fire_count": max(0, int(item.get("fire_count", 0) or 0)),
    }


def ensure_neuron_layout() -> None:
    ensure_memory_layout()
    _read_yaml(NEURON_CONFIG_PATH, _default_neuron_config())
    _read_yaml(NEURON_STATE_PATH, _default_neuron_state())


def read_neuron_config() -> dict[str, Any]:
    ensure_neuron_layout()
    raw = _read_yaml(NEURON_CONFIG_PATH, _default_neuron_config())
    neurons = []
    for item in raw.get("neurons", []):
        normalized = _normalize_neuron_config_item(item)
        if normalized is not None:
            neurons.append(normalized)
    return {
        "version": 1,
        "poll_seconds": float(raw.get("poll_seconds", 1.0) or 1.0),
        "neurons": neurons,
    }


def read_neuron_state() -> dict[str, Any]:
    ensure_neuron_layout()
    raw = _read_yaml(NEURON_STATE_PATH, _default_neuron_state())
    neurons: dict[str, dict[str, Any]] = {}
    raw_neurons = raw.get("neurons", {})
    if isinstance(raw_neurons, dict):
        for neuron_id, item in raw_neurons.items():
            clean_id = str(neuron_id).strip()
            if not clean_id:
                continue
            neurons[clean_id] = _normalize_neuron_state_item(item)
    return {
        "version": 1,
        "neurons": neurons,
    }


def write_neuron_state(payload: dict[str, Any]) -> dict[str, Any]:
    raw_neurons = payload.get("neurons", {})
    neurons: dict[str, dict[str, Any]] = {}
    if isinstance(raw_neurons, dict):
        for neuron_id, item in raw_neurons.items():
            clean_id = str(neuron_id).strip()
            if not clean_id:
                continue
            neurons[clean_id] = _normalize_neuron_state_item(item)
    data = {"version": 1, "neurons": neurons}
    _write_yaml(NEURON_STATE_PATH, data)
    return data
