from datetime import datetime, timedelta, timezone
import random
import unittest
import uuid
from unittest.mock import MagicMock

from telemetry.simulator import EQUIPMENT, generate_sample, write_batch


class SimulatorTests(unittest.TestCase):
    def sample(self, equipment="PUMP-001", elapsed=0, measured_at=None):
        return generate_sample(
            equipment, elapsed, measured_at or datetime.now(timezone.utc),
            uuid.uuid4(), 7, random.Random(12),
        )

    def test_timestamp_is_preserved_in_utc_and_events_are_distinct(self):
        timestamp = datetime(2026, 11, 13, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        first = self.sample(measured_at=timestamp)
        second = self.sample(measured_at=timestamp)
        self.assertEqual(first.measured_at, timestamp)
        self.assertEqual(first.measured_at.utcoffset(), timedelta())
        self.assertNotEqual(first.event_id, second.event_id)
        with self.assertRaises(ValueError):
            self.sample(measured_at=timestamp.replace(tzinfo=None))

    def test_bearing_degradation_has_correlated_evidence_and_recovers(self):
        normal = self.sample(elapsed=0)
        fault = self.sample(elapsed=360)
        self.assertGreater(fault.bearing_temperature_c, 85)
        self.assertGreater(fault.vibration_mm_s, 6)
        self.assertLess(fault.lubricant_pressure_bar, 1.5)
        self.assertGreater(fault.motor_current_a, normal.motor_current_a)
        self.assertGreater(fault.flow_m3_h, 40)
        self.assertEqual(self.sample(elapsed=550).scenario, "normal")
        self.assertAlmostEqual(self.sample(elapsed=600).bearing_temperature_c, normal.bearing_temperature_c)

    def test_suction_fault_differs_from_bearing_fault_and_reference_stays_healthy(self):
        fault = self.sample("PUMP-002", 360)
        self.assertLess(fault.suction_pressure_bar, 0.6)
        self.assertLess(fault.flow_m3_h, 26)
        self.assertLess(fault.discharge_pressure_bar, 4.2)
        self.assertGreater(fault.vibration_mm_s, 5)
        self.assertLess(fault.bearing_temperature_c, 65)
        for elapsed in (0, 120, 240, 300, 419, 480, 540, 600):
            healthy = self.sample("PUMP-003", elapsed)
            self.assertEqual(healthy.scenario, "normal")
            self.assertLess(healthy.vibration_mm_s, 2)

    def test_invalid_inputs_are_rejected(self):
        for elapsed in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.sample(elapsed=elapsed)
        with self.assertRaises(ValueError):
            self.sample("UNKNOWN")

    def test_batch_is_transactional_and_retries_reuse_event_ids(self):
        connection = MagicMock()
        samples = [self.sample(name) for name in EQUIPMENT]
        write_batch(connection, samples)
        write_batch(connection, samples)
        connection.transaction.assert_called()
        calls = connection.cursor.return_value.__enter__.return_value.executemany.call_args_list
        self.assertEqual(calls[0], calls[1])
        self.assertIn("ON CONFLICT DO NOTHING", calls[0].args[0])


if __name__ == "__main__":
    unittest.main()
