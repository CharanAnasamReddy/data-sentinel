from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .deterministic_engine import TestResult, ValidationStatus
from .mappings import ColumnMapping, MappingDocument


@dataclass(frozen=True)
class ValidationTestCase:
    """Declarative test catalog entry used by the self-healing planner."""

    test_id: str
    kind: str
    name: str
    coverage_key: str
    expected_columns: tuple[str, ...] = ()
    source_column: str | None = None
    target_column: str | None = None
    operation: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.test_id,
            self.kind,
            self.name,
            self.coverage_key,
        )):
            raise ValueError("Test cases require non-empty test_id, kind, name, and coverage_key.")
        columns = tuple(self.expected_columns)
        if any(not isinstance(column, str) or not column.strip() for column in columns):
            raise ValueError("expected_columns must contain non-empty column names.")
        object.__setattr__(self, "expected_columns", columns)


@dataclass(frozen=True)
class SelfHealingPlan:
    """An additive test plan; existing cases are never edited or removed."""

    existing_tests: tuple[ValidationTestCase, ...]
    generated_tests: tuple[ValidationTestCase, ...]
    stale_tests: tuple[ValidationTestCase, ...]
    results: tuple[TestResult, ...]

    @property
    def all_tests(self) -> tuple[ValidationTestCase, ...]:
        return self.existing_tests + self.generated_tests


class SelfHealingTestPlanner:
    """Reconcile a declarative test catalog against mapping, schemas, and lineage."""

    def plan(
        self,
        existing_tests: Iterable[ValidationTestCase],
        mapping: MappingDocument,
        source_schema: Iterable[str],
        target_schema: Iterable[str],
        lineage_edges: Iterable[tuple[str, str]],
    ) -> SelfHealingPlan:
        preserved = tuple(existing_tests)
        source_columns = tuple(source_schema)
        target_columns = tuple(target_schema)
        lineage_items = tuple(lineage_edges)
        self._validate_inputs(preserved, source_columns, target_columns, lineage_items)
        lineage = set(lineage_items)

        required = self._required_tests(mapping)
        stale_tests = tuple(
            test for test in preserved
            if self._is_stale(test, required, source_columns, target_columns)
        )
        covered_keys = {
            required_test.coverage_key
            for test in preserved
            if test not in stale_tests
            for required_test in required
            if _covers(test, required_test)
        }
        generated_items = [
            test for test in required
            if test.coverage_key not in covered_keys
        ]
        used_ids = {test.test_id for test in preserved}
        generated: list[ValidationTestCase] = []
        for test in generated_items:
            test_id = test.test_id
            suffix = 2
            while test_id in used_ids:
                test_id = f"{test.test_id}-{suffix}"
                suffix += 1
            used_ids.add(test_id)
            generated.append(
                test if test_id == test.test_id else ValidationTestCase(
                    test_id=test_id,
                    kind=test.kind,
                    name=test.name,
                    coverage_key=test.coverage_key,
                    expected_columns=test.expected_columns,
                    source_column=test.source_column,
                    target_column=test.target_column,
                    operation=test.operation,
                )
            )
        generated_tests = tuple(generated)

        results = tuple(
            self._evaluate(test, mapping, source_columns, target_columns, lineage)
            for test in generated_tests
        ) + tuple(
            TestResult(
                test_id=test.test_id,
                name=test.name,
                status=ValidationStatus.WARN,
                expected=test.expected_columns or None,
                actual=None,
                details=(
                    "Existing test case was preserved but appears stale against the current "
                    "mapping or schema. Review it; a replacement test was generated when needed."
                ),
            )
            for test in stale_tests
        )
        return SelfHealingPlan(
            existing_tests=preserved,
            generated_tests=generated_tests,
            stale_tests=stale_tests,
            results=results,
        )

    @staticmethod
    def _validate_inputs(
        existing_tests: tuple[ValidationTestCase, ...],
        source_schema: tuple[str, ...],
        target_schema: tuple[str, ...],
        lineage_edges: tuple[tuple[str, str], ...],
    ) -> None:
        ids: set[str] = set()
        for test in existing_tests:
            if not test.test_id or not test.coverage_key:
                raise ValueError("Existing test cases require non-empty test_id and coverage_key.")
            if test.test_id in ids:
                raise ValueError(f"Duplicate existing test_id '{test.test_id}'.")
            ids.add(test.test_id)
        for label, columns in (("source_schema", source_schema), ("target_schema", target_schema)):
            if any(not isinstance(column, str) or not column.strip() for column in columns):
                raise ValueError(f"{label} must contain only non-empty column names.")
            if len(set(columns)) != len(columns):
                raise ValueError(f"{label} contains duplicate column names.")
        for edge in lineage_edges:
            if (
                not isinstance(edge, tuple)
                or len(edge) != 2
                or any(not isinstance(column, str) or not column.strip() for column in edge)
            ):
                raise ValueError("Lineage edges must be (source_column, target_column) string pairs.")

    @staticmethod
    def _required_tests(mapping: MappingDocument) -> tuple[ValidationTestCase, ...]:
        cases = [
            ValidationTestCase(
                test_id="AUTO-SOURCE-SCHEMA",
                kind="source_schema",
                name="Validate source schema against mapping",
                coverage_key="schema:source",
                expected_columns=tuple(mapping.source_columns or dict.fromkeys(
                    column for item in mapping.mappings for column in item.source_columns
                )),
            ),
            ValidationTestCase(
                test_id="AUTO-TARGET-SCHEMA",
                kind="target_schema",
                name="Validate target schema against mapping",
                coverage_key="schema:target",
                expected_columns=tuple(mapping.target_columns or (
                    item.target_column for item in mapping.mappings
                )),
            ),
        ]
        for item in mapping.mappings:
            cases.append(
                ValidationTestCase(
                    test_id=f"AUTO-MAPPING-{item.target_column}",
                    kind="mapping",
                    name=f"Validate transformation mapping for {item.target_column}",
                    coverage_key=f"mapping:{item.target_column}",
                    expected_columns=item.source_columns,
                    target_column=item.target_column,
                    operation=item.operation,
                )
            )
            for source_column in item.source_columns:
                cases.append(
                    ValidationTestCase(
                        test_id=f"AUTO-LINEAGE-{source_column}-TO-{item.target_column}",
                        kind="lineage",
                        name=f"Validate lineage {source_column} -> {item.target_column}",
                        coverage_key=f"lineage:{source_column}->{item.target_column}",
                        source_column=source_column,
                        target_column=item.target_column,
                    )
                )
        return tuple(cases)

    @staticmethod
    def _is_stale(
        test: ValidationTestCase,
        required: tuple[ValidationTestCase, ...],
        source_schema: tuple[str, ...],
        target_schema: tuple[str, ...],
    ) -> bool:
        matching_key = next(
            (item for item in required if item.coverage_key == test.coverage_key),
            None,
        )
        if matching_key is not None and test.kind != matching_key.kind:
            return True
        if test.kind == "source_schema":
            current = next(item for item in required if item.coverage_key == "schema:source")
            return (
                test.coverage_key != current.coverage_key
                or test.expected_columns != current.expected_columns
            )
        if test.kind == "target_schema":
            current = next(item for item in required if item.coverage_key == "schema:target")
            return (
                test.coverage_key != current.coverage_key
                or test.expected_columns != current.expected_columns
            )
        if test.kind == "mapping":
            current = next(
                (item for item in required if item.coverage_key == test.coverage_key),
                None,
            )
            return (
                current is None
                or test.expected_columns != current.expected_columns
                or test.target_column != current.target_column
                or test.operation != current.operation
            )
        if test.kind == "lineage":
            current = next(
                (item for item in required if item.coverage_key == test.coverage_key),
                None,
            )
            return (
                current is None
                or test.source_column != current.source_column
                or test.target_column != current.target_column
                or test.source_column not in source_schema
                or test.target_column not in target_schema
            )
        return False

    @staticmethod
    def _evaluate(
        test: ValidationTestCase,
        mapping: MappingDocument,
        source_schema: tuple[str, ...],
        target_schema: tuple[str, ...],
        lineage_edges: set[tuple[str, str]],
    ) -> TestResult:
        if test.kind == "source_schema":
            expected = list(test.expected_columns)
            actual = list(source_schema)
            diff = _schema_difference(expected, actual)
            status = ValidationStatus.PASS if not diff["missing"] and not diff["extra"] else ValidationStatus.FAIL
            details = "Source schema matches the mapping." if status == ValidationStatus.PASS else (
                f"Source schema differs from mapping: missing={diff['missing']}, extra={diff['extra']}."
            )
        elif test.kind == "target_schema":
            expected = list(test.expected_columns)
            actual = list(target_schema)
            diff = _schema_difference(expected, actual)
            status = ValidationStatus.PASS if not diff["missing"] and not diff["extra"] else ValidationStatus.FAIL
            details = "Target schema matches the mapping." if status == ValidationStatus.PASS else (
                f"Target schema differs from mapping: missing={diff['missing']}, extra={diff['extra']}."
            )
        elif test.kind == "mapping":
            item = next(item for item in mapping.mappings if item.target_column == test.target_column)
            missing_sources = [column for column in item.source_columns if column not in source_schema]
            missing_target = item.target_column not in target_schema
            status = ValidationStatus.FAIL if missing_sources or missing_target else ValidationStatus.PASS
            expected = {"source_columns": list(item.source_columns), "target_column": item.target_column}
            actual = {
                "available_source_columns": [column for column in item.source_columns if column in source_schema],
                "target_present": not missing_target,
            }
            diff = {"missing_source_columns": missing_sources, "missing_target": missing_target}
            details = (
                f"Transformation '{item.operation}' can be applied to the current schemas."
                if status == ValidationStatus.PASS
                else f"Mapping schema mismatch: missing_sources={missing_sources}, missing_target={missing_target}."
            )
        elif test.kind == "lineage":
            edge = (test.source_column or "", test.target_column or "")
            status = ValidationStatus.PASS if edge in lineage_edges else ValidationStatus.FAIL
            expected = {"source_column": edge[0], "target_column": edge[1]}
            actual = {"edge_present": edge in lineage_edges}
            diff = None if status == ValidationStatus.PASS else {"missing_lineage_edge": list(edge)}
            details = (
                "Mapping lineage edge exists."
                if status == ValidationStatus.PASS
                else f"Lineage is missing mapping edge {edge[0]} -> {edge[1]}."
            )
        else:
            raise ValueError(f"Unsupported generated test kind '{test.kind}'.")

        return TestResult(
            test_id=test.test_id,
            name=test.name,
            status=status,
            expected=expected,
            actual=actual,
            difference=diff,
            details=details,
        )


def _schema_difference(expected: list[str], actual: list[str]) -> dict[str, list[str]]:
    return {
        "missing": [column for column in expected if column not in actual],
        "extra": [column for column in actual if column not in expected],
    }


def _covers(existing: ValidationTestCase, required: ValidationTestCase) -> bool:
    return (
        existing.kind == required.kind
        and existing.coverage_key == required.coverage_key
        and existing.expected_columns == required.expected_columns
        and existing.source_column == required.source_column
        and existing.target_column == required.target_column
        and existing.operation == required.operation
    )
