import tempfile
import unittest
from datetime import time as dt_time
from pathlib import Path

from stats_store import ReminderSettings, StatsStore


class StatsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = StatsStore(path=Path(self.temp_dir.name) / "stats.json", data={
            "version": 1,
            "total_breaks": 0,
            "total_duration_sec": 0,
            "by_day": {},
            "recent": [],
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_break_shorter_than_one_minute_does_not_increment_break_counts(self):
        self.store.record_break(45, "manual")

        summary = self.store.summary()

        self.assertEqual(summary["total_breaks"], 0)
        self.assertEqual(summary["today_count"], 0)
        self.assertEqual(summary["week_count"], 0)
        self.assertEqual(summary["total_duration_sec"], 45)
        self.assertEqual(summary["today_duration_sec"], 45)
        self.assertEqual(len(summary["recent"]), 1)

    def test_summary_exposes_health_metrics_and_time_buckets(self):
        self.store.record_break(60, "timer")
        self.store.record_break(120, "manual")

        summary = self.store.summary()

        self.assertIn("today_goal_rate", summary)
        self.assertIn("week_goal_rate", summary)
        self.assertIn("week_rate_trend", summary)
        self.assertIn("period_duration_distribution", summary)
        self.assertIn("week_heatmap", summary)
        self.assertEqual(summary["total_breaks"], 2)
        self.assertEqual(summary["today_count"], 2)
        self.assertEqual(len(summary["week_rate_trend"]), 7)
        self.assertEqual(len(summary["period_duration_distribution"]), 3)
        self.assertEqual(len(summary["week_heatmap"]), 7)
        self.assertEqual(len(summary["week_heatmap"][0]["hours"]), 3)

    def test_default_reminder_settings_are_available(self):
        settings = self.store.reminder_settings()

        self.assertEqual(settings.workday_start, "09:00")
        self.assertEqual(settings.workday_end, "18:00")
        self.assertTrue(settings.launch_at_startup)
        self.assertEqual(
            self.store.data["reminder_settings"],
            {
                "workday_start": "09:00",
                "workday_end": "18:00",
                "launch_at_startup": True,
            },
        )

    def test_update_reminder_settings_is_persisted(self):
        settings = ReminderSettings.from_dict(
            {"workday_start": "08:30", "workday_end": "17:45", "launch_at_startup": True}
        )

        self.store.update_reminder_settings(settings)

        reloaded = StatsStore(path=self.store.path, data={})
        reloaded.reload()
        saved = reloaded.reminder_settings()
        self.assertEqual(saved.workday_start, "08:30")
        self.assertEqual(saved.workday_end, "17:45")
        self.assertTrue(saved.launch_at_startup)

    def test_default_reminder_settings_enable_launch_at_startup(self):
        settings = self.store.reminder_settings()

        self.assertTrue(settings.launch_at_startup)
        self.assertEqual(
            self.store.data["reminder_settings"],
            {
                "workday_start": "09:00",
                "workday_end": "18:00",
                "launch_at_startup": True,
            },
        )

    def test_reminder_settings_contains_only_work_hours(self):
        settings = ReminderSettings.from_dict(
            {"workday_start": "09:00", "workday_end": "18:00"}
        )

        self.assertTrue(settings.contains(dt_time(9, 0)))
        self.assertTrue(settings.contains(dt_time(12, 30)))
        self.assertFalse(settings.contains(dt_time(8, 59)))
        self.assertFalse(settings.contains(dt_time(18, 0)))

    def test_reminder_settings_supports_overnight_windows(self):
        settings = ReminderSettings.from_dict(
            {"workday_start": "22:00", "workday_end": "06:00"}
        )

        self.assertTrue(settings.contains(dt_time(22, 0)))
        self.assertTrue(settings.contains(dt_time(1, 15)))
        self.assertFalse(settings.contains(dt_time(12, 0)))


if __name__ == "__main__":
    unittest.main()