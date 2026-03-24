from __future__ import annotations

import math
import random
import threading
from datetime import datetime, time as dt_time, timedelta
from typing import Any

from memory.memory_store import (
    DAY_ROLLOVER_HOUR,
    active_memory_day,
    archive_day_to_month,
    list_temp_session_stats,
    now_dt,
    now_iso,
    parse_iso,
    read_day_summary,
    read_state,
)
from scheduler.neuron_store import ensure_neuron_layout, read_neuron_config, read_neuron_state, write_neuron_state


def _memory_day_start(now: datetime) -> datetime:
    current_day = active_memory_day(now)
    date_value = datetime.fromisoformat(f"{current_day}T00:00:00").date()
    return datetime.combine(date_value, dt_time(hour=DAY_ROLLOVER_HOUR), tzinfo=now.tzinfo)


class SchedulerService:
    def __init__(self, *, heart_service, sleep_service) -> None:
        ensure_neuron_layout()
        self.heart_service = heart_service
        self.sleep_service = sleep_service
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            name="scheduler-worker",
            daemon=True,
        )
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._started = False

    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            config = read_neuron_config()
            state = read_neuron_state()

            archive_day_to_month()

            poll_seconds = max(0.2, float(config.get("poll_seconds", 1.0) or 1.0))
            current = now_dt()
            neuron_state_map = dict(state.get("neurons", {}))

            for neuron in config.get("neurons", []):
                neuron_id = str(neuron.get("id", "")).strip()
                if not neuron_id:
                    continue

                runtime = dict(neuron_state_map.get(neuron_id, {}))
                runtime.setdefault("accumulator", 0.0)
                runtime.setdefault("fire_count", 0)

                raw_signal, payload = self._measure_signal(neuron, current)
                last_evaluated_at = parse_iso(runtime.get("last_evaluated_at"))
                delta_seconds = max(0.1, (current - last_evaluated_at).total_seconds()) if last_evaluated_at else poll_seconds

                decay = max(0.0, min(1.0, float(neuron.get("decay", 0.95) or 0.95)))
                gain = max(0.0, float(neuron.get("gain", 0.1) or 0.1))
                max_accumulator = max(0.1, float(neuron.get("max_accumulator", 5.0) or 5.0))
                accumulator = float(runtime.get("accumulator", 0.0) or 0.0)
                accumulator = accumulator * math.pow(decay, delta_seconds) + raw_signal * gain * delta_seconds
                accumulator = max(0.0, min(max_accumulator, accumulator))

                base_probability = max(0.0, float(neuron.get("base_probability", 0.0) or 0.0))
                probability_gain = max(0.0, float(neuron.get("probability_gain", 0.1) or 0.1))
                max_probability = max(0.0, min(1.0, float(neuron.get("max_probability", 1.0) or 1.0)))
                probability = min(max_probability, base_probability + accumulator * probability_gain)

                cooldown_seconds = max(1, int(neuron.get("cooldown_seconds", 60) or 60))
                last_fired_at = parse_iso(runtime.get("last_fired_at"))
                cooldown_ready = last_fired_at is None or (current - last_fired_at) >= timedelta(seconds=cooldown_seconds)
                should_fire = bool(neuron.get("enabled", False)) and raw_signal > 0 and cooldown_ready and random.random() < probability

                if should_fire:
                    self._dispatch(
                        neuron=neuron,
                        impulse=accumulator,
                        payload=payload,
                    )
                    runtime["last_fired_at"] = current.isoformat(timespec="seconds")
                    runtime["fire_count"] = int(runtime.get("fire_count", 0) or 0) + 1
                    accumulator = max(0.0, float(neuron.get("post_fire_accumulator", 0.0) or 0.0))

                runtime["accumulator"] = accumulator
                runtime["last_signal"] = raw_signal
                runtime["last_probability"] = probability
                runtime["last_evaluated_at"] = current.isoformat(timespec="seconds")
                neuron_state_map[neuron_id] = runtime

            write_neuron_state({"version": 1, "neurons": neuron_state_map})
            if self._stop_event.wait(poll_seconds):
                break

    def _dispatch(self, *, neuron: dict[str, Any], impulse: float, payload: dict[str, Any]) -> None:
        target_service = str(neuron.get("target_service", "")).strip()
        runner = str(neuron.get("runner", "")).strip()
        source = str(neuron.get("id", "")).strip()

        if target_service == "sleep":
            self.sleep_service.submit_task(
                runner=runner,
                source=source,
                impulse=impulse,
                payload=payload,
            )
            return

        if target_service == "heart":
            self.heart_service.submit_interrupt(
                runner=runner,
                source=source,
                impulse=impulse,
                payload=payload,
            )

    def _measure_signal(self, neuron: dict[str, Any], current: datetime) -> tuple[float, dict[str, Any]]:
        neuron_id = str(neuron.get("id", "")).strip()
        if neuron_id == "temp_overflow_pressure":
            return self._measure_temp_overflow_pressure()
        if neuron_id == "day_closure_pressure":
            return self._measure_day_closure_pressure(current)
        if neuron_id == "subjective_pulse":
            return self._measure_subjective_pulse(current)
        return 0.0, {}

    def _measure_temp_overflow_pressure(self) -> tuple[float, dict[str, Any]]:
        stats = list_temp_session_stats()
        if not stats:
            return 0.0, {}

        best = max(
            stats,
            key=lambda item: (
                int(item.get("count", 0) or 0),
                int(item.get("oldest_age_seconds", 0) or 0),
            ),
        )
        count = int(best.get("count", 0) or 0)
        if count <= 0:
            return 0.0, {}

        oldest_age = int(best.get("oldest_age_seconds", 0) or 0)
        count_signal = min(1.0, count / 8.0)
        age_signal = min(1.0, oldest_age / 3600.0)
        signal = max(0.0, min(1.0, count_signal * 0.65 + age_signal * 0.35))
        payload = {
            "session_id": str(best.get("session_id", "")).strip(),
            "temp_round_count": count,
            "oldest_age_seconds": oldest_age,
            "measured_at": now_iso(),
        }
        return signal, payload

    def _measure_day_closure_pressure(self, current: datetime) -> tuple[float, dict[str, Any]]:
        state = read_state()
        memory_day_start = _memory_day_start(current)
        memory_day_end = memory_day_start + timedelta(days=1)
        seconds_until_rollover = max(0.0, (memory_day_end - current).total_seconds())
        rollover_signal = 1.0 - min(1.0, seconds_until_rollover / (6 * 3600))

        last_user = parse_iso(state.get("last_user_message_at"))
        last_assistant = parse_iso(state.get("last_assistant_message_at"))
        latest_activity = max((item for item in [last_user, last_assistant] if item is not None), default=None)
        activity_signal = 1.0 if latest_activity is not None and latest_activity >= memory_day_start else 0.0

        summary = read_day_summary().strip()
        unsummarized_signal = 1.0 if not summary or summary == "- （待整理）" else 0.35
        signal = max(0.0, min(1.0, activity_signal * (0.2 + 0.5 * rollover_signal + 0.3 * unsummarized_signal)))
        payload = {
            "seconds_until_rollover": int(seconds_until_rollover),
            "activity_signal": round(activity_signal, 3),
            "rollover_signal": round(rollover_signal, 3),
            "summary_state": "placeholder" if unsummarized_signal >= 1.0 else "existing",
            "measured_at": now_iso(),
        }
        return signal, payload

    def _measure_subjective_pulse(self, current: datetime) -> tuple[float, dict[str, Any]]:
        state = read_state()
        last_heart = parse_iso(state.get("last_heartbeat_at"))
        last_user = parse_iso(state.get("last_user_message_at"))
        last_assistant = parse_iso(state.get("last_assistant_message_at"))
        latest_activity = max((item for item in [last_user, last_assistant] if item is not None), default=None)

        quiet_signal = 0.0
        if last_heart is not None:
            quiet_signal = min(1.0, max(0.0, (current - last_heart).total_seconds()) / 1800.0)
        else:
            quiet_signal = 0.4

        recent_activity_signal = 0.0
        if latest_activity is not None:
            recent_activity_signal = max(0.0, 1.0 - min(1.0, (current - latest_activity).total_seconds() / (6 * 3600)))

        signal = max(0.0, min(1.0, quiet_signal * 0.7 + recent_activity_signal * 0.3))
        payload = {
            "quiet_signal": round(quiet_signal, 3),
            "recent_activity_signal": round(recent_activity_signal, 3),
            "measured_at": now_iso(),
        }
        return signal, payload
