"""护眼休息统计数据：本地 JSON 持久化。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


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
            }
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
        day["count"] += 1
        day["duration_sec"] += duration_sec
        self.data["total_breaks"] = int(self.data.get("total_breaks", 0)) + 1
        self.data["total_duration_sec"] = int(self.data.get("total_duration_sec", 0)) + duration_sec
        ended = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        self.data["last_break_ended_at"] = ended
        self.data["last_break_duration_sec"] = duration_sec
        self.data["last_trigger"] = trigger
        recent = self.data.setdefault("recent", [])
        recent.insert(
            0,
            {
                "at": ended,
                "duration_sec": duration_sec,
                "trigger": trigger,
            },
        )
        self.data["recent"] = recent[:50]
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        tmp.replace(self.path)

    def summary(self) -> dict[str, Any]:
        by_day = self.data.get("by_day", {})
        if not isinstance(by_day, dict):
            by_day = {}
        today = date.today().isoformat()
        td = by_day.get(today)
        if not isinstance(td, dict):
            td = {"count": 0, "duration_sec": 0}
        today_count = int(td.get("count", 0))
        today_sec = int(td.get("duration_sec", 0))

        week_count = 0
        week_sec = 0
        week_trend = []
        for i in range(6, -1, -1):
            dk = (date.today() - timedelta(days=i)).isoformat()
            x = by_day.get(dk)
            if isinstance(x, dict):
                c = int(x.get("count", 0))
                ms = int(x.get("duration_sec", 0))
                week_count += c
                week_sec += ms
                week_trend.append({"date": dk[5:], "count": c, "duration": ms})
            else:
                week_trend.append({"date": dk[5:], "count": 0, "duration": 0})

        recent = self.data.get("recent", [])
        if not isinstance(recent, list):
            recent = []

        return {
            "total_breaks": int(self.data.get("total_breaks", 0)),
            "total_duration_sec": int(self.data.get("total_duration_sec", 0)),
            "today_count": today_count,
            "today_duration_sec": today_sec,
            "week_count": week_count,
            "week_duration_sec": week_sec,
            "week_trend": week_trend,
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

