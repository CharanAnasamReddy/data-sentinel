from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .deterministic_engine import TestResult, ValidationStatus


@dataclass
class AIInsight:
    summary: str
    recommended_actions: list[str] = field(default_factory=list)
    business_explanation: str = ""
    confidence: float = 0.0


class AIAgent:
    """AI layer that interprets deterministic results without overriding them."""

    def analyze(self, result: TestResult, context: dict[str, Any] | None = None) -> AIInsight:
        context = context or {}
        if result.status == ValidationStatus.FAIL:
            summary = f"Deterministic validation found a failure in {result.name}."
            recommended_actions = [
                "Review the transformation or source data causing the mismatch.",
                "Run impacted downstream checks for dependent tables.",
                "Confirm whether a regression was introduced by the latest change.",
            ]
            business_explanation = (
                "The system detected a material mismatch between expected and actual data. "
                "This should be investigated before treating the pipeline as healthy."
            )
            confidence = 0.94
        elif result.status == ValidationStatus.PASS:
            summary = f"Deterministic validation confirmed {result.name} is healthy."
            recommended_actions = [
                "Continue monitoring the pipeline for trend drift.",
                "Keep the existing regression suite active.",
            ]
            business_explanation = "The objective validation checks passed; the process remains aligned to its expected output."
            confidence = 0.9
        else:
            summary = f"Validation for {result.name} requires manual review."
            recommended_actions = ["Inspect the validation inputs and rule configuration."]
            business_explanation = "The rule did not yield a definitive pass/fail result, so human review is warranted."
            confidence = 0.75

        if "business_context" in context:
            business_explanation = (
                f"{business_explanation} Context: {context['business_context']}"
            )

        return AIInsight(
            summary=summary,
            recommended_actions=recommended_actions,
            business_explanation=business_explanation,
            confidence=confidence,
        )

    def interpret(self, result: TestResult, context: dict[str, Any] | None = None) -> AIInsight:
        return self.analyze(result, context)

    def enhance(self, result: TestResult, context: dict[str, Any] | None = None) -> AIInsight:
        return self.analyze(result, context)

    def explain_impact(self, result: TestResult) -> list[str]:
        if result.status != ValidationStatus.FAIL:
            return ["No material impact identified by deterministic validation."]
        return [
            f"The failing check '{result.name}' may affect downstream consumers of the impacted data.",
            "Assess provenance and lineage of the record sets involved.",
            "Prioritize upstream root-cause analysis before rerunning dependent jobs.",
        ]
