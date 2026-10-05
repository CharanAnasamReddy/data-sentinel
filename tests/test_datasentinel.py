import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from datasentinel.ai_agent import AIAgent
from datasentinel.cli import run_example, run_self_healing_plan
from datasentinel.connections import ConnectionSettings
from datasentinel.deterministic_engine import (
    DeterministicTestingEngine,
    ValidationStatus,
)
from datasentinel.events import EventStore
from datasentinel.mappings import load_mapping_document, parse_mapping_document
from datasentinel.self_healing import SelfHealingTestPlanner, ValidationTestCase
from datasentinel.visualization import ExecutiveDashboard


class ConnectionSettingsTests(unittest.TestCase):
    def test_connection_strings_load_from_environment_mapping(self):
        settings = ConnectionSettings.from_environment({
            "DATASENTINEL_SOURCE_CONNECTION_STRING": "source-secret",
            "DATASENTINEL_TARGET_CONNECTION_STRING": "target-secret",
        })

        self.assertEqual(
            settings.require_source_and_target(),
            ("source-secret", "target-secret"),
        )
        self.assertNotIn("source-secret", repr(settings))
        self.assertNotIn("target-secret", repr(settings))

    def test_named_adf_ssis_and_glue_integrations_load_together(self):
        configuration = {
            "etl_integrations": [
                {
                    "name": "adf-prod",
                    "provider": "adf",
                    "settings": {"factory_name": "factory-a"},
                    "credentials_env": {"client_secret": "ADF_SECRET"},
                },
                {
                    "name": "ssis-warehouse",
                    "provider": "ssis",
                    "settings": {"server": "ssis.example"},
                    "credentials_env": {"password": "SSIS_PASSWORD"},
                },
                {
                    "name": "glue-analytics",
                    "provider": "aws_glue",
                    "settings": {"region": "us-east-1"},
                    "credentials_env": {"secret_key": "AWS_SECRET"},
                },
            ]
        }
        environment = {
            "ADF_SECRET": "adf-secret-value",
            "SSIS_PASSWORD": "ssis-secret-value",
            "AWS_SECRET": "glue-secret-value",
        }

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "integrations.json"
            config_path.write_text(json.dumps(configuration), encoding="utf-8")
            settings = ConnectionSettings.from_environment(
                environ=environment,
                integrations_path=config_path,
            )

        self.assertEqual(
            [(item.name, item.provider) for item in settings.etl_integrations],
            [
                ("adf-prod", "adf"),
                ("ssis-warehouse", "ssis"),
                ("glue-analytics", "aws_glue"),
            ],
        )
        self.assertEqual(
            settings.get_etl_integration("adf-prod").credentials["client_secret"],
            "adf-secret-value",
        )
        self.assertEqual(len(settings.enabled_etl_integrations), 3)
        self.assertNotIn("adf-secret-value", repr(settings))

    def test_etl_integrations_are_optional_and_provider_is_extensible(self):
        settings = ConnectionSettings.from_environment({})
        self.assertEqual(settings.etl_integrations, ())

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "integrations.json"
            config_path.write_text(
                '{"etl_integrations":[{"name":"custom","provider":"future_tool"}]}',
                encoding="utf-8",
            )
            configured = ConnectionSettings.from_environment(integrations_path=config_path)

        self.assertEqual(configured.get_etl_integration("custom").provider, "future_tool")
        with self.assertRaisesRegex(KeyError, "not configured"):
            configured.get_etl_integration("missing")

    def test_disabled_integration_does_not_require_credential_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "integrations.json"
            config_path.write_text(
                '{"etl_integrations":[{"name":"adf-disabled","provider":"adf",'
                '"enabled":false,"credentials_env":{"client_secret":"ADF_CLIENT_SECRET"}}]}',
                encoding="utf-8",
            )
            settings = ConnectionSettings.from_environment(
                environ={},
                integrations_path=config_path,
            )

        self.assertEqual(len(settings.etl_integrations), 1)
        self.assertFalse(settings.etl_integrations[0].enabled)
        self.assertEqual(settings.enabled_etl_integrations, ())

    def test_duplicate_integration_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "integrations.json"
            config_path.write_text(
                '{"etl_integrations":['
                '{"name":"same","provider":"adf"},'
                '{"name":"same","provider":"ssis"}]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate ETL integration name"):
                ConnectionSettings.from_environment(integrations_path=config_path)

    def test_missing_integration_credential_reports_variable_without_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "integrations.json"
            config_path.write_text(
                '{"etl_integrations":[{"name":"adf","provider":"adf",'
                '"credentials_env":{"client_secret":"ADF_CLIENT_SECRET"}}]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "ADF_CLIENT_SECRET"):
                ConnectionSettings.from_environment(
                    environ={},
                    integrations_path=config_path,
                )

    def test_missing_connection_strings_raise_clear_error_without_values(self):
        settings = ConnectionSettings.from_environment({})

        with self.assertRaisesRegex(
            ValueError,
            "DATASENTINEL_SOURCE_CONNECTION_STRING.*DATASENTINEL_TARGET_CONNECTION_STRING",
        ) as error:
            settings.require_source_and_target()

        self.assertNotIn("secret", str(error.exception))

    def test_blank_connection_strings_are_treated_as_missing(self):
        settings = ConnectionSettings.from_environment({
            "DATASENTINEL_SOURCE_CONNECTION_STRING": " ",
            "DATASENTINEL_TARGET_CONNECTION_STRING": "target-secret",
        })

        with self.assertRaisesRegex(
            ValueError,
            "DATASENTINEL_SOURCE_CONNECTION_STRING",
        ):
            settings.require_source_and_target()


class MappingDocumentTests(unittest.TestCase):
    def test_json_mapping_builds_and_applies_deterministic_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "customer.json"
            path.write_text(json.dumps({
                "name": "customer mapping",
                "source_columns": ["first_name", "last_name", "gross", "tax"],
                "target_columns": ["full_name", "net"],
                "mappings": [
                    {
                        "source_columns": ["first_name", "last_name"],
                        "target_column": "full_name",
                        "transform": {"op": "concat", "separator": " "},
                        "target_type": "varchar(50)",
                        "target_length": 50,
                    },
                    {
                        "source_columns": ["gross", "tax"],
                        "target_column": "net",
                        "transform": "subtract",
                        "target_type": "decimal(12,2)",
                    },
                ],
            }), encoding="utf-8")
            mapping = load_mapping_document(path)

        rules = mapping.build_transformation_rules()
        output = {
            target: rule({
                "first_name": "Ada",
                "last_name": "Lovelace",
                "gross": "100.25",
                "tax": "10.25",
            })
            for target, rule in rules.items()
        }

        self.assertEqual(output["full_name"], "Ada Lovelace")
        self.assertEqual(output["net"], Decimal("90.00"))
        self.assertEqual(mapping.transform_record({
            "first_name": "Ada",
            "last_name": "Lovelace",
            "gross": "100.25",
            "tax": "10.25",
        }), output)

    def test_csv_mapping_normalizes_common_headers_and_generates_trim_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "names.csv"
            path.write_text(
                "Source Column,Target Column,Transformation Rule,Target Data Type\n"
                "raw_name,clean_name,trim,string\n",
                encoding="utf-8",
            )
            mapping = load_mapping_document(path)

        self.assertEqual(
            mapping.transform_record({"raw_name": "  DataSentinel  "}),
            {"clean_name": "DataSentinel"},
        )

    def test_csv_mapping_supports_encoded_multi_source_transformations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "amounts.csv"
            path.write_text(
                'Source Columns,Target Column,Transformation Rule,Target Data Type\n'
                '"[""gross"",""tax""]",net,"{""op"":""subtract""}",decimal(12,2)\n',
                encoding="utf-8",
            )
            mapping = load_mapping_document(path)

        self.assertEqual(
            mapping.transform_record({"gross": "125.50", "tax": "25.50"}),
            {"net": Decimal("100.00")},
        )

    def test_mapping_validates_schema_and_required_target_constraints(self):
        mapping = parse_mapping_document({
            "source_columns": ["name"],
            "target_columns": ["name"],
            "mappings": [{
                "source_column": "name",
                "target_column": "name",
                "nullable": False,
                "target_length": 5,
            }],
        })

        self.assertEqual(
            mapping.validate_source_schema(["name", "unexpected"]),
            {"missing": [], "extra": ["unexpected"]},
        )
        with self.assertRaisesRegex(ValueError, "produced null"):
            mapping.transform_record({"name": None})
        with self.assertRaisesRegex(ValueError, "exceeds its configured length"):
            mapping.transform_record({"name": "too long"})

    def test_unsupported_executable_expression_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported transformation"):
            parse_mapping_document({
                "mappings": [{
                    "source_column": "name",
                    "target_column": "name",
                    "transform": "__import__('os').system('echo unsafe')",
                }],
            })

    def test_duplicate_target_mappings_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "mapped more than once"):
            parse_mapping_document({
                "mappings": [
                    {"source_column": "first", "target_column": "name"},
                    {"source_column": "last", "target_column": "name"},
                ],
            })

    def test_yaml_mapping_is_supported_when_optional_dependency_is_installed(self):
        if importlib.util.find_spec("yaml") is None:
            self.skipTest("Install the mappings extra to test YAML mapping support.")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.yaml"
            path.write_text(
                "name: yaml-map\nmappings:\n"
                "  - source_column: name\n"
                "    target_column: name\n"
                "    transform: upper\n",
                encoding="utf-8",
            )
            mapping = load_mapping_document(path)
        self.assertEqual(mapping.transform_record({"name": "ada"}), {"name": "ADA"})

    def test_excel_mapping_is_supported_when_optional_dependency_is_installed(self):
        if importlib.util.find_spec("openpyxl") is None:
            self.skipTest("Install the mappings extra to test Excel mapping support.")
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.append(["Source Column", "Target Column", "Transformation Rule"])
            worksheet.append(["name", "name", "upper"])
            workbook.save(path)
            mapping = load_mapping_document(path)

        self.assertEqual(mapping.transform_record({"name": "ada"}), {"name": "ADA"})


class SelfHealingTestPlannerTests(unittest.TestCase):
    def setUp(self):
        self.mapping = parse_mapping_document({
            "source_columns": ["first_name", "last_name"],
            "target_columns": ["full_name"],
            "mappings": [{
                "source_columns": ["first_name", "last_name"],
                "target_column": "full_name",
                "transform": {"op": "concat", "separator": " "},
            }],
        })
        self.planner = SelfHealingTestPlanner()

    def test_generates_missing_schema_mapping_and_lineage_tests(self):
        plan = self.planner.plan(
            existing_tests=(),
            mapping=self.mapping,
            source_schema=["first_name", "last_name"],
            target_schema=["full_name"],
            lineage_edges=[
                ("first_name", "full_name"),
                ("last_name", "full_name"),
            ],
        )

        self.assertEqual(len(plan.generated_tests), 5)
        self.assertEqual(
            {result.status for result in plan.results},
            {ValidationStatus.PASS},
        )
        self.assertEqual(plan.all_tests, plan.generated_tests)

    def test_preserves_existing_tests_and_only_adds_gaps(self):
        existing = ValidationTestCase(
            test_id="CUSTOM-SOURCE",
            kind="source_schema",
            name="Existing source schema test",
            coverage_key="schema:source",
            expected_columns=("first_name", "last_name"),
        )

        plan = self.planner.plan(
            existing_tests=[existing],
            mapping=self.mapping,
            source_schema=["first_name", "last_name"],
            target_schema=["full_name"],
            lineage_edges=[
                ("first_name", "full_name"),
                ("last_name", "full_name"),
            ],
        )

        self.assertIs(plan.existing_tests[0], existing)
        self.assertEqual(plan.existing_tests[0], existing)
        self.assertNotIn("schema:source", {test.coverage_key for test in plan.generated_tests})
        self.assertEqual(len(plan.generated_tests), 4)
        self.assertEqual(plan.stale_tests, ())

    def test_marks_outdated_case_stale_but_keeps_it_and_adds_replacement(self):
        old_case = ValidationTestCase(
            test_id="CUSTOM-SOURCE",
            kind="source_schema",
            name="Original source schema test",
            coverage_key="schema:source",
            expected_columns=("old_name",),
        )

        plan = self.planner.plan(
            existing_tests=[old_case],
            mapping=self.mapping,
            source_schema=["first_name", "last_name"],
            target_schema=["full_name"],
            lineage_edges=[],
        )

        self.assertEqual(plan.existing_tests, (old_case,))
        self.assertEqual(plan.stale_tests, (old_case,))
        self.assertIn(old_case, plan.all_tests)
        self.assertIn("schema:source", {test.coverage_key for test in plan.generated_tests})
        stale_results = [result for result in plan.results if result.test_id == old_case.test_id]
        self.assertEqual(stale_results[0].status, ValidationStatus.WARN)

    def test_generated_tests_fail_for_schema_and_lineage_drift(self):
        plan = self.planner.plan(
            existing_tests=(),
            mapping=self.mapping,
            source_schema=["first_name"],
            target_schema=["wrong_target"],
            lineage_edges=[("first_name", "full_name")],
        )

        failed = {result.test_id: result for result in plan.results if result.status == ValidationStatus.FAIL}
        self.assertIn("AUTO-SOURCE-SCHEMA", failed)
        self.assertIn("AUTO-TARGET-SCHEMA", failed)
        self.assertTrue(any(result.test_id.startswith("AUTO-MAPPING-") for result in failed.values()))
        self.assertTrue(any(result.test_id.startswith("AUTO-LINEAGE-last_name") for result in failed.values()))

    def test_replanning_same_inputs_is_idempotent(self):
        first = self.planner.plan([], self.mapping, ["first_name", "last_name"], ["full_name"], [])
        second = self.planner.plan([], self.mapping, ["first_name", "last_name"], ["full_name"], [])

        self.assertEqual(first.generated_tests, second.generated_tests)
        self.assertEqual(
            [(result.test_id, result.status, result.details) for result in first.results],
            [(result.test_id, result.status, result.details) for result in second.results],
        )

    def test_cli_plan_reads_mapping_schema_lineage_and_existing_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping_path = root / "mapping.json"
            source_schema_path = root / "source-schema.json"
            target_schema_path = root / "target-schema.json"
            lineage_path = root / "lineage.json"
            catalog_path = root / "test-catalog.json"
            expanded_catalog_path = root / "test-catalog-expanded.json"
            mapping_path.write_text(json.dumps({
                "source_columns": ["first_name", "last_name"],
                "target_columns": ["full_name"],
                "mappings": [{
                    "source_columns": ["first_name", "last_name"],
                    "target_column": "full_name",
                    "transform": {"op": "concat", "separator": " "},
                }],
            }), encoding="utf-8")
            source_schema_path.write_text(
                '{"columns":["first_name","last_name"]}', encoding="utf-8"
            )
            target_schema_path.write_text('{"columns":["full_name"]}', encoding="utf-8")
            lineage_path.write_text(
                '{"edges":[["first_name","full_name"],["last_name","full_name"]]}',
                encoding="utf-8",
            )
            catalog_path.write_text(json.dumps({"tests": [{
                "test_id": "EXISTING-SCHEMA",
                "kind": "source_schema",
                "name": "existing source check",
                "coverage_key": "schema:source",
                "expected_columns": ["first_name", "last_name"],
            }]}), encoding="utf-8")

            result = run_self_healing_plan(
                str(mapping_path),
                str(source_schema_path),
                str(target_schema_path),
                str(lineage_path),
                str(catalog_path),
                str(expanded_catalog_path),
            )

        self.assertEqual(result["existing_tests"][0]["test_id"], "EXISTING-SCHEMA")
        self.assertEqual(len(result["generated_tests"]), 4)
        self.assertTrue(all(item["status"] == "PASS" for item in result["results"]))
        saved_catalog = json.loads(expanded_catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved_catalog["tests"]), 5)
        self.assertEqual(saved_catalog["tests"][0]["test_id"], "EXISTING-SCHEMA")

    def test_self_healing_never_overwrites_existing_test_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping_path = root / "mapping.json"
            source_schema_path = root / "source-schema.json"
            target_schema_path = root / "target-schema.json"
            lineage_path = root / "lineage.json"
            output_catalog_path = root / "test-catalog.json"
            mapping_path.write_text(json.dumps({
                "mappings": [{"source_column": "source", "target_column": "target"}],
            }), encoding="utf-8")
            source_schema_path.write_text('{"columns":["source"]}', encoding="utf-8")
            target_schema_path.write_text('{"columns":["target"]}', encoding="utf-8")
            lineage_path.write_text('{"edges":[["source","target"]]}', encoding="utf-8")
            output_catalog_path.write_text("keep existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                run_self_healing_plan(
                    str(mapping_path),
                    str(source_schema_path),
                    str(target_schema_path),
                    str(lineage_path),
                    write_test_catalog_path=str(output_catalog_path),
                )

            self.assertEqual(output_catalog_path.read_text(encoding="utf-8"), "keep existing")


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
