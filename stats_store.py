"""护眼休息统计数据：本地 JSON 持久化。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any


MIN_COUNTED_BREAK_SEC = 60
DEFAULT_DAILY_BREAK_GOAL = 8
PERIOD_LABELS = ("上午", "下午", "晚上")
DEFAULT_WORKDAY_START_MINUTES = 9 * 60
DEFAULT_WORKDAY_END_MINUTES = 18 * 60


def _empty_periods() -> dict[str, int]:
    return {"上午": 0, "下午": 0, "晚上": 0}


def _period_for_hour(hour: int) -> str:
    if 5 <= hour < 12:
        return "上午"
    if 12 <= hour < 18:
        return "下午"
    return "晚上"


def _coerce_event(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    at = entry.get("at")
    if not isinstance(at, str) or not at:
        return None
    try:
        ended_at = datetime.fromisoformat(at)
    except ValueError:
        return None
    duration_sec = max(0, int(entry.get("duration_sec", 0)))
    trigger = str(entry.get("trigger", ""))
    return {
        "at": at,
        "ended_at": ended_at,
        "duration_sec": duration_sec,
        "trigger": trigger,
        "counted": duration_sec >= MIN_COUNTED_BREAK_SEC,
        "period": _period_for_hour(ended_at.hour),
    }


def _format_clock_minutes(total_minutes: int) -> str:
    normalized = int(total_minutes) % (24 * 60)
    hour, minute = divmod(normalized, 60)
    return f"{hour:02d}:{minute:02d}"


def _parse_clock_minutes(value: Any, fallback: int) -> int:
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour < 24 and 0 <= minute < 60:
                return hour * 60 + minute
    return fallback


def _parse_bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return fallback


@dataclass(frozen=True)
class ReminderSettings:
    workday_start_minutes: int = DEFAULT_WORKDAY_START_MINUTES
    workday_end_minutes: int = DEFAULT_WORKDAY_END_MINUTES
    launch_at_startup: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReminderSettings:
        payload = data if isinstance(data, dict) else {}
        return cls(
            workday_start_minutes=_parse_clock_minutes(
                payload.get("workday_start"),
                DEFAULT_WORKDAY_START_MINUTES,
            ),
            workday_end_minutes=_parse_clock_minutes(
                payload.get("workday_end"),
                DEFAULT_WORKDAY_END_MINUTES,
            ),
            launch_at_startup=_parse_bool(payload.get("launch_at_startup"), True),
        )

    @property
    def workday_start(self) -> str:
        return _format_clock_minutes(self.workday_start_minutes)

    @property
    def workday_end(self) -> str:
        return _format_clock_minutes(self.workday_end_minutes)

    def to_dict(self) -> dict[str, str]:
        return {
            "workday_start": self.workday_start,
            "workday_end": self.workday_end,
            "launch_at_startup": self.launch_at_startup,
        }

    def contains(self, current_time: datetime | dt_time | None = None) -> bool:
        if current_time is None:
            now = datetime.now().time()
        elif isinstance(current_time, datetime):
            now = current_time.time()
        else:
            now = current_time

        minutes = now.hour * 60 + now.minute
        start = self.workday_start_minutes
        end = self.workday_end_minutes
        if start == end:
            return True
        if start < end:
            return start <= minutes < end
        return minutes >= start or minutes < end


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "EyeRest"
    return Path.home() / ".eyerest"


@dataclass
class StatsStore:
    path: Path
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> StatsStore:
        directory = default_data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "stats.json"
        data: dict[str, Any] = {}
        if path.exists():
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (json.JSONDecodeError, OSError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        if "by_day" not in data:
            data = {
                "version": 1,
                "total_breaks": 0,
                "total_duration_sec": 0,
                "by_day": {},
                "recent": [],
                "history": [],
            }
        data.setdefault("history", [])
        settings = ReminderSettings.from_dict(data.get("reminder_settings"))
        data["reminder_settings"] = settings.to_dict()
        return cls(path=path, data=data)

    def reload(self) -> None:
        if not self.path.exists():
            return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    def record_break(self, duration_sec: int, trigger: str) -> None:
        duration_sec = max(0, int(duration_sec))
        today = date.today().isoformat()
        by_day = self.data.setdefault("by_day", {})
        day = by_day.setdefault(today, {"count": 0, "duration_sec": 0})
        if duration_sec >= MIN_COUNTED_BREAK_SEC:
            day["count"] += 1
        day["duration_sec"] += duration_sec
        if duration_sec >= MIN_COUNTED_BREAK_SEC:
            self.data["total_breaks"] = int(self.data.get("total_breaks", 0)) + 1
        self.data["total_duration_sec"] = int(self.data.get("total_duration_sec", 0)) + duration_sec
        ended = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        self.data["last_break_ended_at"] = ended
        self.data["last_break_duration_sec"] = duration_sec
        self.data["last_trigger"] = trigger
        event = {
            "at": ended,
            "duration_sec": duration_sec,
            "trigger": trigger,
        }
        recent = self.data.setdefault("recent", [])
        recent.insert(0, event)
        self.data["recent"] = recent[:50]
        history = self.data.setdefault("history", [])
        history.insert(0, event)
        self.data["history"] = history[:365]
        self._save()

    def reminder_settings(self) -> ReminderSettings:
        settings = ReminderSettings.from_dict(self.data.get("reminder_settings"))
        self.data["reminder_settings"] = settings.to_dict()
        return settings

    def update_reminder_settings(self, settings: ReminderSettings) -> ReminderSettings:
        normalized = ReminderSettings.from_dict(settings.to_dict())
        self.data["reminder_settings"] = normalized.to_dict()
        self._save()
        return normalized

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        tmp.replace(self.path)

    def summary(self, daily_goal: int = DEFAULT_DAILY_BREAK_GOAL) -> dict[str, Any]:
        by_day = self.data.get("by_day", {})
        if not isinstance(by_day, dict):
            by_day = {}
        today = date.today().isoformat()
        td = by_day.get(today)
        if not isinstance(td, dict):
            td = {"count": 0, "duration_sec": 0}
        today_count = int(td.get("count", 0))
        today_sec = int(td.get("duration_sec", 0))

        history = self.data.get("history", [])
        if not isinstance(history, list):
            history = []
        if not history:
            fallback_recent = self.data.get("recent", [])
            history = fallback_recent if isinstance(fallback_recent, list) else []

        parsed_history = []
        for item in history:
            event = _coerce_event(item)
            if event is not None:
                parsed_history.append(event)

        daily_goal = max(0, int(daily_goal))
        week_count = 0
        week_sec = 0
        week_trend = []
        week_rate_trend = []
        week_heatmap = []
        period_duration_distribution = _empty_periods()
        for i in range(6, -1, -1):
            current_day = date.today() - timedelta(days=i)
            dk = current_day.isoformat()
            x = by_day.get(dk)
            if isinstance(x, dict):
                c = int(x.get("count", 0))
                ms = int(x.get("duration_sec", 0))
                week_count += c
                week_sec += ms
                week_trend.append({"date": dk[5:], "count": c, "duration": ms})
                rate = min(1.0, c / daily_goal) if daily_goal else 0.0
                week_rate_trend.append({"date": dk[5:], "rate": rate, "count": c})
            else:
                week_trend.append({"date": dk[5:], "count": 0, "duration": 0})
                week_rate_trend.append({"date": dk[5:], "rate": 0.0, "count": 0})

            bucket_hours = []
            for period in PERIOD_LABELS:
                duration_total = 0
                count_total = 0
                for event in parsed_history:
                    if event["ended_at"].date() != current_day:
                        continue
                    if event["period"] != period:
                        continue
                    duration_total += event["duration_sec"]
                    if event["counted"]:
                        count_total += 1
                bucket_hours.append({
                    "period": period,
                    "count": count_total,
                    "duration_sec": duration_total,
                })
                period_duration_distribution[period] += duration_total
            week_heatmap.append({"date": dk[5:], "hours": bucket_hours})

        recent = self.data.get("recent", [])
        if not isinstance(recent, list):
            recent = []

        distribution = [
            {"period": period, "duration_sec": period_duration_distribution[period]}
            for period in PERIOD_LABELS
        ]
        today_goal_rate = min(1.0, today_count / daily_goal) if daily_goal else 0.0
        week_goal_rate = min(1.0, week_count / (daily_goal * 7)) if daily_goal else 0.0

        return {
            "total_breaks": int(self.data.get("total_breaks", 0)),
            "total_duration_sec": int(self.data.get("total_duration_sec", 0)),
            "today_count": today_count,
            "today_duration_sec": today_sec,
            "today_goal_rate": today_goal_rate,
            "week_count": week_count,
            "week_duration_sec": week_sec,
            "week_goal_rate": week_goal_rate,
            "week_trend": week_trend,
            "week_rate_trend": week_rate_trend,
            "period_duration_distribution": distribution,
            "week_heatmap": week_heatmap,
            "last_break_ended_at": self.data.get("last_break_ended_at"),
            "recent": recent,
        }


def format_duration(sec: int) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return "< 1 分钟"
    m, _ = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h} 小时 {m} 分钟"
    return f"{m} 分钟"

