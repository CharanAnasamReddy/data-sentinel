import unittest

from datasentinel.ai_agent import AIAgent
from datasentinel.deterministic_engine import DeterministicTestingEngine, ValidationStatus
from datasentinel.events import EventStore


class DataSentinelTests(unittest.TestCase):
    def test_row_count_failure_is_deterministic(self):
        engine = DeterministicTestingEngine()
        result = engine.validate_row_count(
            test_id="TC-001",
            name="row_count",
            source_count=1_000_000,
            target_count=998_432,
        )

        self.assertEqual(result.status, ValidationStatus.FAIL)
        self.assertEqual(result.expected, 1_000_000)
        self.assertEqual(result.actual, 998_432)
        self.assertEqual(result.difference, 568)

    def test_pass_result_is_not_overridden_by_ai(self):
        engine = DeterministicTestingEngine()
        result = engine.validate_row_count(
            test_id="TC-002",
            name="row_count_pass",
            source_count=100,
            target_count=100,
        )
        insight = AIAgent().analyze(result)

        self.assertEqual(result.status, ValidationStatus.PASS)
        self.assertIn("healthy", insight.summary)

    def test_event_store_tracks_execution_state(self):
        store = EventStore()
        store.emit("TEST_STARTED", "Engine started")
        store.emit("SCHEMA_VALIDATION_COMPLETED", "Schema validated", {"result": "ok"})

        self.assertEqual(len(store.history()), 2)
        self.assertEqual(store.history()[0].event_type, "TEST_STARTED")
        self.assertEqual(store.history()[1].payload["result"], "ok")


if __name__ == "__main__":
    unittest.main()
