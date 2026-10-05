import unittest

from datasentinel.ai_agent import AIAgent
from datasentinel.cli import run_example
from datasentinel.deterministic_engine import (
    DeterministicTestingEngine,
    ValidationStatus,
)
from datasentinel.events import EventStore
from datasentinel.visualization import ExecutiveDashboard


class DeterministicValidationTests(unittest.TestCase):
    def setUp(self):
        engine = DeterministicTestingEngine()
        self.engine = engine

    def test_src_03_ext_01_cmp_01_row_counts_reconcile(self):
        result = self.engine.validate_row_count(
            test_id="CMP-01",
            name="source_to_target_count",
            source_count=100,
            target_count=100,
        )

        self.assertEqual(result.status, ValidationStatus.PASS)
        self.assertEqual(result.difference, 0)

    def test_ext_01_cmp_01_row_count_mismatch_reports_exact_difference(self):
        result = self.engine.validate_row_count(
            test_id="TC-001",
            name="row_count",
            source_count=1_000_000,
            target_count=998_432,
        )

        self.assertEqual(result.status, ValidationStatus.FAIL)
        self.assertEqual(result.expected, 1_000_000)
        self.assertEqual(result.actual, 998_432)
        self.assertEqual(result.difference, 1_568)
        self.assertIn("1568", result.details)

    def test_src_05_empty_source_and_target_are_a_valid_zero_count(self):
        result = self.engine.validate_row_count(
            test_id="SRC-05",
            name="empty_source",
            source_count=0,
            target_count=0,
        )

        self.assertEqual(result.status, ValidationStatus.PASS)

    def test_src_02_schema_validation_reports_missing_and_extra_columns(self):
        result = self.engine.validate_schema(
            test_id="SRC-02",
            name="source_schema",
            expected_columns=["id", "email"],
            actual_columns=["id", "legacy_email"],
        )

        self.assertEqual(result.status, ValidationStatus.FAIL)
        self.assertEqual(result.difference, {
            "missing": ["email"],
            "extra": ["legacy_email"],
        })

    def test_src_02_schema_validation_passes_when_columns_match(self):
        result = self.engine.validate_schema(
            test_id="SRC-02",
            name="source_schema",
            expected_columns=["id", "email"],
            actual_columns=["id", "email"],
        )

        self.assertEqual(result.status, ValidationStatus.PASS)

    def test_cmp_03_null_count_comparison(self):
        matching = self.engine.validate_nulls(
            "CMP-03", "null_count", expected_null_count=2, actual_null_count=2
        )
        mismatching = self.engine.validate_nulls(
            "CMP-03", "null_count", expected_null_count=2, actual_null_count=3
        )

        self.assertEqual(matching.status, ValidationStatus.PASS)
        self.assertEqual(mismatching.status, ValidationStatus.FAIL)
        self.assertEqual(mismatching.difference, 1)

    def test_dq_01_duplicate_count_validation(self):
        clean = self.engine.validate_duplicates(
            "DQ-01", "business_key_duplicates", expected_duplicate_count=0, actual_duplicate_count=0
        )
        duplicates_found = self.engine.validate_duplicates(
            "DQ-01", "business_key_duplicates", expected_duplicate_count=0, actual_duplicate_count=2
        )

        self.assertEqual(clean.status, ValidationStatus.PASS)
        self.assertEqual(duplicates_found.status, ValidationStatus.FAIL)
        self.assertEqual(duplicates_found.difference, 2)

    def test_unregistered_rule_raises_a_clear_error(self):
        with self.assertRaisesRegex(KeyError, "not registered"):
            self.engine.run_rule("unknown", {})

    def test_batch_marks_unregistered_rule_as_error(self):
        results = self.engine.run_batch([
            {"test_id": "ERR-01", "name": "invalid_record", "rule_name": "missing_rule"},
        ])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, ValidationStatus.ERROR)
        self.assertIn("missing_rule", results[0].details)


class ExecutionAndReportingTests(unittest.TestCase):
    def test_reg_01_deterministic_results_are_serializable(self):
        result = DeterministicTestingEngine().validate_row_count(
            test_id="REG-01",
            name="baseline_count",
            source_count=42,
            target_count=42,
        )

        serialized = result.to_dict()
        self.assertEqual(serialized["test_id"], "REG-01")
        self.assertEqual(serialized["status"], "PASS")
        self.assertEqual(serialized["difference"], 0)
        self.assertIn("executed_at", serialized)

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

    def test_ai_interprets_failure_without_changing_deterministic_status(self):
        result = DeterministicTestingEngine().validate_row_count(
            test_id="CMP-01",
            name="source_to_target_count",
            source_count=10,
            target_count=8,
        )
        insight = AIAgent().analyze(result)

        self.assertEqual(result.status, ValidationStatus.FAIL)
        self.assertIn("failure", insight.summary)
        self.assertTrue(insight.recommended_actions)

    def test_err_05_event_store_tracks_execution_events_in_order(self):
        store = EventStore()
        store.emit("TEST_STARTED", "Engine started")
        store.emit("SCHEMA_VALIDATION_COMPLETED", "Schema validated", {"result": "ok"})

        self.assertEqual(len(store.history()), 2)
        self.assertEqual(store.history()[0].event_type, "TEST_STARTED")
        self.assertEqual(store.history()[1].payload["result"], "ok")

    def test_rpt_01_dashboard_summarizes_status_from_deterministic_results(self):
        engine = DeterministicTestingEngine()
        passed = engine.validate_row_count("RPT-01-P", "passed", 5, 5)
        failed = engine.validate_row_count("RPT-01-F", "failed", 5, 4)
        insight = AIAgent().analyze(failed)

        report = ExecutiveDashboard().render(
            [passed, failed],
            {failed.test_id: insight},
        )

        panels = {panel["title"]: panel["value"] for panel in report["panels"]}
        self.assertEqual(panels["Passed checks"], "1")
        self.assertEqual(panels["Failed checks"], "1")
        self.assertEqual(report["summary"][1]["status"], "FAIL")
        self.assertIn("business_explanation", report["summary"][1])

    def test_example_run_reports_exact_count_difference_and_events(self):
        output = run_example()

        self.assertEqual(output["deterministic_result"]["status"], "FAIL")
        self.assertEqual(output["deterministic_result"]["difference"], 1_568)
        self.assertEqual(output["events"][0]["event_type"], "TEST_STARTED")


if __name__ == "__main__":
    unittest.main()
