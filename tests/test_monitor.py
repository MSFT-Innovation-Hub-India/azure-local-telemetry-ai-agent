from datetime import datetime, timedelta, timezone
import unittest

from fastapi.testclient import TestClient

from telemetry import monitor
from telemetry.app import app
from telemetry.rules import RULES


NOW = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
BEARING = next(rule for rule in RULES if rule.id == "bearing")
SAMPLE = {"bearing_temperature_c": 80.0, "vibration_mm_s": 2.0}


def bucket_row(equipment_id, position, violated):
    start = int(NOW.timestamp()) - 60
    row = {"equipment_id": equipment_id, "bucket": datetime.fromtimestamp(start + position * 5, timezone.utc)}
    row.update({f"c{i}": condition in violated for i, condition in enumerate(monitor.CONDITIONS)})
    return row


def result(rows, alerts=(), latest=None):
    sample = dict.fromkeys(("speed_rpm", "motor_current_a", "motor_temperature_c", "suction_pressure_bar",
                            "discharge_pressure_bar", "flow_m3_h", "lubricant_pressure_bar", "ambient_temperature_c"), 1.0)
    sample.update(measured_at=NOW, **(SAMPLE if latest is None else latest))
    return monitor.build(NOW, 60, rows, {"PUMP-001": sample}, list(alerts), ["PUMP-001", "PUMP-003"])


class MonitorTests(unittest.TestCase):
    def test_combined_lane_needs_every_condition_and_streak_counts_trailing_run(self):
        temperature, vibration = BEARING.warning
        rows = [bucket_row("PUMP-001", p, {temperature}) for p in range(0, 7)]
        rows += [bucket_row("PUMP-001", p, {temperature, vibration}) for p in range(7, 12)]
        bearing = result(rows)["equipment"][0]["rules"][0]
        self.assertEqual(bearing["conditions"][0][:12], [1] * 12)
        self.assertEqual(bearing["conditions"][1][:12], [0] * 7 + [1] * 5)
        self.assertEqual(bearing["warning"]["series"][:12], [0] * 7 + [1] * 5)
        self.assertIsNone(bearing["warning"]["series"][12])
        self.assertEqual(bearing["warning"]["streak_seconds"], 25)
        self.assertEqual(bearing["critical"]["streak_seconds"], 0)

    def test_current_state_open_alert_and_missing_data_are_reported(self):
        alert = {"equipment_id": "PUMP-001", "rule_id": "bearing", "severity": "warning",
                 "opened_at": NOW - timedelta(seconds=40), "acknowledged_at": None}
        data = result([], [alert], {"bearing_temperature_c": 80.0, "vibration_mm_s": 5.0})
        pump = data["equipment"][0]["rules"][0]
        self.assertEqual(pump["warning"]["met"], [True, True])
        self.assertEqual(pump["critical"]["met"], [False, False])
        self.assertEqual(pump["alert"]["severity"], "warning")
        quiet = data["equipment"][1]
        self.assertIsNone(quiet["latest"])
        self.assertIsNone(quiet["rules"][0]["alert"])
        self.assertEqual(set(quiet["rules"][0]["warning"]["series"]), {None})

    def test_thresholds_come_from_the_detector_rules_and_window_is_bounded(self):
        self.assertEqual({t["value"] for t in monitor.thresholds()["bearing_temperature_c"]}, {75, 85})
        client = TestClient(app)
        self.assertEqual(client.get("/api/rules/monitor?minutes=0").status_code, 422)
        self.assertEqual(client.get("/api/rules/monitor?minutes=31").status_code, 422)


if __name__ == "__main__":
    unittest.main()
