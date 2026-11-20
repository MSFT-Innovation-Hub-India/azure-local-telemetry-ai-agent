from datetime import datetime, timedelta, timezone
import unittest

from telemetry.rules import RULES, severity, summarize, sustained


NOW = datetime(2026, 11, 13, 7, 0, tzinfo=timezone.utc)
NORMAL = dict(
    speed_rpm=1480, motor_current_a=18, motor_temperature_c=63, bearing_temperature_c=59,
    vibration_mm_s=1.8, suction_pressure_bar=1.5, discharge_pressure_bar=5.8,
    flow_m3_h=42, lubricant_pressure_bar=2.4, ambient_temperature_c=27,
)


def samples(seconds=40, **values):
    return [
        dict(NORMAL, measured_at=NOW - timedelta(seconds=age), quality="good",
             operating_state="running", **values)
        for age in range(seconds, -1, -2)
    ]


class RuleTests(unittest.TestCase):
    def test_exact_bearing_thresholds_and_required_durations(self):
        rule = RULES[0]
        self.assertIsNone(severity(rule, samples(28, bearing_temperature_c=75, vibration_mm_s=4), NOW))
        self.assertEqual(severity(rule, samples(30, bearing_temperature_c=75, vibration_mm_s=4), NOW), "warning")
        self.assertIsNone(severity(rule, samples(40, bearing_temperature_c=74.99, vibration_mm_s=4), NOW))
        self.assertIsNone(severity(rule, samples(18, bearing_temperature_c=85, vibration_mm_s=6), NOW))
        self.assertEqual(severity(rule, samples(20, bearing_temperature_c=85, vibration_mm_s=6), NOW), "critical")

    def test_suction_needs_all_related_trigger_parameters(self):
        rule = RULES[1]
        self.assertIsNone(severity(rule, samples(40, suction_pressure_bar=.5, flow_m3_h=42, vibration_mm_s=6), NOW))
        self.assertEqual(severity(rule, samples(30, suction_pressure_bar=1, flow_m3_h=34), NOW), "warning")
        self.assertEqual(severity(rule, samples(20, suction_pressure_bar=.6, flow_m3_h=28, vibration_mm_s=4.5), NOW), "critical")

    def test_gap_bad_quality_and_staleness_invalidate_sustained_observation(self):
        rows = samples(40, bearing_temperature_c=90, vibration_mm_s=7)
        self.assertIsNone(severity(RULES[0], [r for r in rows if not NOW-timedelta(seconds=16) <= r["measured_at"] <= NOW-timedelta(seconds=8)], NOW))
        rows[-1]["quality"] = "bad"
        self.assertIsNone(severity(RULES[0], rows, NOW))
        self.assertIsNone(severity(RULES[0], samples(40, bearing_temperature_c=90, vibration_mm_s=7), NOW+timedelta(seconds=16)))

    def test_hysteresis_does_not_clear_on_partial_recovery_or_missing_data(self):
        rule = RULES[0]
        self.assertFalse(sustained(samples(40, bearing_temperature_c=72, vibration_mm_s=2.5), rule.clear, 30, NOW))
        self.assertTrue(sustained(samples(30, bearing_temperature_c=70, vibration_mm_s=3), rule.clear, 30, NOW))
        self.assertFalse(sustained([], rule.clear, 30, NOW))

    def test_evidence_does_not_include_scenario_or_future_readings(self):
        rows = samples(40)
        rows[-1]["scenario"] = "fake-ground-truth"
        future = dict(rows[-1], measured_at=NOW+timedelta(seconds=20), bearing_temperature_c=199)
        evidence = summarize(rows+[future], NOW)
        self.assertEqual(evidence["signals"]["bearing_temperature_c"]["max"], 59)
        self.assertNotIn("scenario", str(evidence))


if __name__ == "__main__":
    unittest.main()
