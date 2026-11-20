from datetime import datetime, timezone
import json
import threading
import unittest
import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from telemetry.app import app
from telemetry.knowledge import DependencyError, ROOT, chunks, parse_completion
from telemetry.store import save_alert


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.state.models = {key: {"id": key} for key in ("qwen2-5-0-5b-cpu", "qwen2-5-14b-cpu")}
        app.state.model_lock = threading.Lock()
        app.state.collection = "telemetry-sops-" + "a" * 24
        app.state.knowledge = MagicMock()
        self.source = {"document_id": "SOP-PMP-002", "revision": "1.0", "section": "BEARING", "text": "Test SOP source"}
        app.state.passages = [self.source]
        app.state.knowledge.retrieve.return_value = [self.source]

    def test_document_sections_are_usable_for_indexing_and_rule_citations(self):
        catalog = json.loads((ROOT / "sops" / "catalog.json").read_text())
        passages = []
        for item in catalog["documents"]:
            passages.extend(chunks(dict(item, content=(ROOT / "sops" / item["file"]).read_text())))
        for section in ("BEARING", "SUCTION", "DATA-QUALITY"):
            self.assertTrue(any(p["section"] == section for p in passages))
        self.assertTrue(all(len(p["text"]) < 3200 for p in passages))

    def test_chosen_model_is_used_and_diagnosis_keeps_sources_and_evidence(self):
        identifier = uuid.uuid4()
        now = datetime.now(timezone.utc)
        alert = {
            "id": identifier, "equipment_id": "PUMP-001", "rule_id": "bearing", "rule_revision": "1.0",
            "severity": "critical", "opened_at": now, "resolved_at": None, "impact": "Possible wear",
            "evidence": {"sample_count": 16}, "related_parameters": ["lubricant_pressure_bar"],
            "missing_evidence": ["Inspection"], "source_document": "SOP-PMP-002",
            "source_revision": "1.0", "source_section": "BEARING", "title": "Bearing condition",
        }
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [alert, {"now": now}]
        conn.execute.return_value.fetchall.return_value = []
        with patch("telemetry.app.connect") as connect, patch("telemetry.app.complete", return_value=("Advisory [S1]", None)) as model:
            connect.return_value.__enter__.return_value = conn
            response = self.client.post(f"/api/alerts/{identifier}/diagnose", json={"model": "qwen2-5-14b-cpu"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(model.call_args.args[0]["id"], "qwen2-5-14b-cpu")
        self.assertEqual(response.json()["sources"][0]["section"], "BEARING")
        self.assertEqual(response.json()["evidence"]["current_observations"]["sample_count"], 0)
        self.assertFalse(app.state.model_lock.locked())

    def test_unknown_model_and_busy_state_are_explicit(self):
        endpoint = f"/api/alerts/{uuid.uuid4()}/diagnose"
        self.assertEqual(self.client.post(endpoint, json={"model": "unconfigured"}).status_code, 422)
        app.state.model_lock.acquire()
        try:
            self.assertEqual(self.client.post(endpoint, json={"model": "qwen2-5-0-5b-cpu"}).status_code, 409)
        finally:
            app.state.model_lock.release()

    def test_cross_origin_acknowledgement_is_rejected(self):
        response = self.client.post(
            f"/api/alerts/{uuid.uuid4()}/acknowledge", json={}, headers={"Origin": "https://unrelated.invalid"},
        )
        self.assertEqual(response.status_code, 403)

    def test_active_critical_alert_is_not_downgraded_or_duplicated(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = {"id": uuid.uuid4(), "severity": "critical"}
        save_alert(conn, "PUMP-001", "bearing", "warning", "Bearing", "Wear",
                   "SOP-PMP-002", "BEARING", {}, (), (), datetime.now(timezone.utc))
        self.assertEqual(conn.execute.call_count, 2)
        self.assertEqual(conn.execute.call_args.args[1][0], "critical")

    def test_streamed_deltas_sources_usage_and_truncation_are_explicit(self):
        events = [
            {"choices": [{"delta": {"role": "assistant", "content": "Possible bearing "}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "concern [S1]."}, "finish_reason": "length"}]},
            {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}},
        ]
        lines = ["data: " + json.dumps(event) for event in events] + ["data: [DONE]"]
        text, usage = parse_completion(lines, 1)
        self.assertIn("Possible bearing concern [S1].", text)
        self.assertIn("Application notice", text)
        self.assertEqual(usage["total_tokens"], 48)
        with self.assertRaises(DependencyError):
            parse_completion(lines[:-1], 1)
        with self.assertRaises(DependencyError):
            parse_completion(lines, 0)


if __name__ == "__main__":
    unittest.main()
