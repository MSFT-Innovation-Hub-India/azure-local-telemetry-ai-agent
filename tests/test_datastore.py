from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import psycopg

from telemetry import datastore
from telemetry.app import app


def result(one=None, many=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = one
    cursor.fetchall.return_value = many
    return cursor


class DataStoreTests(unittest.TestCase):
    def setUp(self):
        datastore._closed.update(cutoff=None, expires=0.0, counts={})
        self.now = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
        self.cutoff = self.now.replace(hour=0)

    def connection(self, storage_error=False):
        conn = MagicMock()
        responses = iter([
            result(one={"now": self.now, "cutoff": self.cutoff}),
            result(many=[{"equipment_id": "PUMP-001", "n": 100}]),
            result(many=[{"equipment_id": "PUMP-001", "n": 40, "recent": 30}]),
            result(many=[{"equipment_id": "PUMP-001", "description": "Pump", "first_sample": self.now - timedelta(days=2), "latest_sample": self.now}]),
        ])

        def execute(sql, params=None):
            if "hypertable_size" in sql and storage_error:
                raise psycopg.errors.InsufficientPrivilege("denied")
            if "hypertable_size" in sql:
                return result(one={"samples_bytes": 10, "database_bytes": 20})
            if "timescaledb_information.chunks" in sql:
                return result(one={"chunks": 3})
            if "policy_retention" in sql:
                return result(one={"retention": "7 days"})
            return next(responses)

        conn.execute.side_effect = execute
        return conn

    def test_total_is_closed_days_plus_exact_rows_from_today(self):
        with patch("telemetry.datastore.connect") as connect:
            connect.return_value.__enter__.return_value = self.connection()
            data = datastore.summary()
        self.assertEqual(data["total_rows"], 140)
        self.assertEqual(data["equipment"][0]["rows_last_minute"], 30)
        self.assertEqual(data["storage"]["retention"], "7 days")

    def test_closed_day_counts_are_cached_between_polls(self):
        with patch("telemetry.datastore.connect") as connect:
            conn = self.connection()
            connect.return_value.__enter__.return_value = conn
            datastore.summary()
            first = conn.execute.call_count
            datastore._closed_counts(conn, self.cutoff)
        self.assertEqual(conn.execute.call_count, first)

    def test_storage_metadata_failure_does_not_hide_row_counts(self):
        with patch("telemetry.datastore.connect") as connect:
            connect.return_value.__enter__.return_value = self.connection(storage_error=True)
            data = datastore.summary()
        self.assertEqual(data["total_rows"], 140)
        self.assertIsNone(data["storage"]["database_bytes"])

    def test_recent_endpoint_rejects_unknown_equipment_and_bad_limits(self):
        client = TestClient(app)
        with patch("telemetry.app.datastore.recent", return_value=None):
            self.assertEqual(client.get("/api/data/recent?equipment_id=NOPE").status_code, 404)
        self.assertEqual(client.get("/api/data/recent?equipment_id=PUMP-001&limit=101").status_code, 422)


if __name__ == "__main__":
    unittest.main()
