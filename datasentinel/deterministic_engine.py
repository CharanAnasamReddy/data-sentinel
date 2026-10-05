from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Mapping


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class TestResult:
    test_id: str
    name: str
    status: ValidationStatus
    expected: Any | None = None
    actual: Any | None = None
    difference: Any | None = None
    details: str = ""
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "status": self.status.value,
            "expected": self.expected,
            "actual": self.actual,
            "difference": self.difference,
            "details": self.details,
            "executed_at": self.executed_at.isoformat(),
        }


class DeterministicTestingEngine:
    """Source of truth for data validation outcomes."""

    def __init__(self) -> None:
        self._rules: dict[str, Callable[[Any], TestResult]] = {}

    def register_rule(self, rule_name: str, checker: Callable[[Any], TestResult]) -> None:
        self._rules[rule_name] = checker

    def validate(self, *args: Any, **kwargs: Any) -> TestResult:
        return self.validate_row_count(*args, **kwargs)

    def compare_row_counts(self, test_id: str, name: str, source_count: int, target_count: int) -> TestResult:
        return self.validate_row_count(test_id, name, source_count, target_count)

    def validate_row_count(self, test_id: str, name: str, source_count: int, target_count: int) -> TestResult:
        difference = int(target_count) - int(source_count)
        status = ValidationStatus.PASS if source_count == target_count else ValidationStatus.FAIL
        details = (
            "Row count matches expected source count."
            if status == ValidationStatus.PASS
            else f"Row count mismatch detected: target is {abs(difference)} rows different from source."
        )
        return TestResult(
            test_id=test_id,
            name=name,
            status=status,
            expected=source_count,
            actual=target_count,
            difference=abs(difference),
            details=details,
        )

    def validate_schema(self, test_id: str, name: str, expected_columns: Iterable[str], actual_columns: Iterable[str]) -> TestResult:
        expected = list(expected_columns)
        actual = list(actual_columns)
        missing = [column for column in expected if column not in actual]
        extra = [column for column in actual if column not in expected]
        status = ValidationStatus.PASS if not missing and not extra else ValidationStatus.FAIL
        details = "Schema matches expected structure." if status == ValidationStatus.PASS else (
            f"Schema differences detected: missing={missing}, extra={extra}"
        )
        return TestResult(
            test_id=test_id,
            name=name,
            status=status,
            expected=expected,
            actual=actual,
            difference={"missing": missing, "extra": extra},
            details=details,
        )

    def validate_nulls(self, test_id: str, name: str, expected_null_count: int, actual_null_count: int) -> TestResult:
        status = ValidationStatus.PASS if expected_null_count == actual_null_count else ValidationStatus.FAIL
        difference = abs(int(actual_null_count) - int(expected_null_count))
        return TestResult(
            test_id=test_id,
            name=name,
            status=status,
            expected=expected_null_count,
            actual=actual_null_count,
            difference=difference,
            details=(
                "Null counts are within expectation."
                if status == ValidationStatus.PASS
                else "Null count does not match expected value."
            ),
        )

    def validate_duplicates(self, test_id: str, name: str, expected_duplicate_count: int, actual_duplicate_count: int) -> TestResult:
        status = ValidationStatus.PASS if expected_duplicate_count == actual_duplicate_count else ValidationStatus.FAIL
        difference = abs(int(actual_duplicate_count) - int(expected_duplicate_count))
        return TestResult(
            test_id=test_id,
            name=name,
            status=status,
            expected=expected_duplicate_count,
            actual=actual_duplicate_count,
            difference=difference,
            details=(
                "Duplicate counts match expectations."
                if status == ValidationStatus.PASS
                else "Duplicate count differs from expected value."
            ),
        )

    def run_rule(self, rule_name: str, payload: Any) -> TestResult:
        if rule_name not in self._rules:
            raise KeyError(f"Rule '{rule_name}' is not registered.")
        return self._rules[rule_name](payload)

    def run_batch(self, tests: Iterable[Mapping[str, Any]]) -> list[TestResult]:
        results: list[TestResult] = []
        for test in tests:
            rule_name = test["rule_name"]
            payload = test.get("payload")
            if rule_name not in self._rules:
                results.append(
                    TestResult(
                        test_id=str(test.get("test_id", "UNKNOWN")),
                        name=str(test.get("name", rule_name)),
                        status=ValidationStatus.ERROR,
                        expected=None,
                        actual=None,
                        difference=None,
                        details=f"Rule '{rule_name}' is not registered.",
                    )
                )
                continue
            result = self._rules[rule_name](payload)
            results.append(result)
        return results
