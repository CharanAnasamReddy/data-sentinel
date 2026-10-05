from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .ai_agent import AIAgent
from .deterministic_engine import DeterministicTestingEngine
from .events import EventStore
from .mappings import load_mapping_document
from .self_healing import SelfHealingTestPlanner, ValidationTestCase
from .visualization import ExecutiveDashboard


def run_example() -> dict:
    engine = DeterministicTestingEngine()
    event_store = EventStore()
    ai_agent = AIAgent()
    dashboard = ExecutiveDashboard()

    event_store.emit("TEST_STARTED", "Starting deterministic validation run")

    row_result = engine.validate_row_count(
        test_id="TC-001",
        name="Row count validation",
        source_count=1_000_000,
        target_count=998_432,
    )
    event_store.emit("ROW_COUNT_VALIDATED", "Completed row count validation", {"status": row_result.status.value})

    insight = ai_agent.analyze(row_result, {"business_context": "The pipeline is under active investigation."})
    dashboard_payload = dashboard.render([row_result], {row_result.test_id: insight})

    return {
        "deterministic_result": row_result.to_dict(),
        "ai_insight": insight.__dict__,
        "executive_dashboard": dashboard_payload,
        "events": event_store.snapshot(),
    }


def run_self_healing_plan(
    mapping_path: str,
    source_schema_path: str,
    target_schema_path: str,
    lineage_path: str,
    test_catalog_path: str | None = None,
    write_test_catalog_path: str | None = None,
) -> dict[str, Any]:
    mapping = load_mapping_document(mapping_path)
    source_schema = _load_schema(source_schema_path)
    target_schema = _load_schema(target_schema_path)
    lineage_document = _load_json_object(lineage_path, "lineage")
    edges = lineage_document.get("edges")
    if not isinstance(edges, list):
        raise ValueError("Lineage document must contain an 'edges' array.")
    lineage_edges = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(value, str) for value in edge):
            raise ValueError(f"Lineage edge at index {index} must be a two-item string array.")
        lineage_edges.append((edge[0], edge[1]))

    existing_tests = []
    if test_catalog_path:
        catalog = _load_json_object(test_catalog_path, "test catalog")
        tests = catalog.get("tests")
        if not isinstance(tests, list):
            raise ValueError("Test catalog must contain a 'tests' array.")
        existing_tests = [_load_test_case(entry, index) for index, entry in enumerate(tests)]

    plan = SelfHealingTestPlanner().plan(
        existing_tests,
        mapping,
        source_schema,
        target_schema,
        lineage_edges,
    )
    output = {
        "existing_tests": [_test_case_to_dict(test) for test in plan.existing_tests],
        "generated_tests": [_test_case_to_dict(test) for test in plan.generated_tests],
        "stale_test_ids": [test.test_id for test in plan.stale_tests],
        "results": [result.to_dict() for result in plan.results],
    }
    if write_test_catalog_path:
        output_path = Path(write_test_catalog_path)
        catalog = {"tests": [_test_case_to_dict(test) for test in plan.all_tests]}
        serialized = json.dumps(catalog, indent=2, default=str) + "\n"
        with output_path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        output["written_test_catalog"] = str(output_path)
    return output


def _load_json_object(path: str, description: str) -> dict[str, Any]:
    try:
        content = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {description} document '{path}'.") from error
    if not isinstance(content, dict):
        raise ValueError(f"{description.capitalize()} document must contain a JSON object.")
    return content


def _load_schema(path: str) -> list[str]:
    document = _load_json_object(path, "schema")
    columns = document.get("columns")
    if not isinstance(columns, list) or any(not isinstance(column, str) for column in columns):
        raise ValueError(f"Schema document '{path}' must contain a string array named 'columns'.")
    return columns


def _load_test_case(entry: Any, index: int) -> ValidationTestCase:
    if not isinstance(entry, dict):
        raise ValueError(f"Test catalog entry at index {index} must be an object.")
    for field_name in ("test_id", "kind", "name", "coverage_key"):
        if not isinstance(entry.get(field_name), str) or not entry[field_name].strip():
            raise ValueError(
                f"Test catalog entry at index {index} requires a non-empty '{field_name}'."
            )
    expected_columns = entry.get("expected_columns", [])
    if not isinstance(expected_columns, list) or any(
        not isinstance(column, str) for column in expected_columns
    ):
        raise ValueError(f"'expected_columns' in test catalog entry {index} must be a string array.")
    for field_name in ("source_column", "target_column", "operation"):
        value = entry.get(field_name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"'{field_name}' in test catalog entry {index} must be a string.")
    try:
        return ValidationTestCase(
            test_id=entry["test_id"],
            kind=entry["kind"],
            name=entry["name"],
            coverage_key=entry["coverage_key"],
            expected_columns=tuple(expected_columns),
            source_column=entry.get("source_column"),
            target_column=entry.get("target_column"),
            operation=entry.get("operation"),
        )
    except (KeyError, TypeError) as error:
        raise ValueError(
            f"Test catalog entry at index {index} requires test_id, kind, name, and coverage_key."
        ) from error


def _test_case_to_dict(test: ValidationTestCase) -> dict[str, Any]:
    return {
        "test_id": test.test_id,
        "kind": test.kind,
        "name": test.name,
        "coverage_key": test.coverage_key,
        "expected_columns": list(test.expected_columns),
        "source_column": test.source_column,
        "target_column": test.target_column,
        "operation": test.operation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="data-sentinel deterministic ETL testing engine")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--example", action="store_true", help="Run a sample validation cycle")
    commands.add_argument(
        "--validate-mapping",
        metavar="PATH",
        help="Validate a JSON, YAML, CSV, or Excel mapping document and show generated rules",
    )
    commands.add_argument(
        "--heal-tests",
        metavar="MAPPING",
        help="Generate an additive self-healing test plan from a mapping document",
    )
    parser.add_argument("--source-schema", help="JSON schema file with a string 'columns' array")
    parser.add_argument("--target-schema", help="JSON schema file with a string 'columns' array")
    parser.add_argument("--lineage", help="JSON lineage file with an 'edges' array of [source, target]")
    parser.add_argument("--test-catalog", help="Optional JSON test catalog to preserve and reconcile")
    parser.add_argument(
        "--write-test-catalog",
        help="Write preserved plus generated cases to a new JSON file; existing files are never overwritten",
    )
    args = parser.parse_args()

    if args.example:
        print(json.dumps(run_example(), indent=2, default=str))
        return

    if args.validate_mapping:
        try:
            mapping = load_mapping_document(args.validate_mapping)
        except (OSError, ValueError, RuntimeError) as error:
            parser.error(str(error))
        print(json.dumps(mapping.summary(), indent=2, default=str))
        return

    if args.heal_tests:
        missing = [
            flag for flag, value in (
                ("--source-schema", args.source_schema),
                ("--target-schema", args.target_schema),
                ("--lineage", args.lineage),
            )
            if not value
        ]
        if missing:
            parser.error(f"--heal-tests requires {' '.join(missing)}.")
        try:
            plan = run_self_healing_plan(
                args.heal_tests,
                args.source_schema,
                args.target_schema,
                args.lineage,
                args.test_catalog,
                args.write_test_catalog,
            )
        except (OSError, ValueError, RuntimeError) as error:
            parser.error(str(error))
        print(json.dumps(plan, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
