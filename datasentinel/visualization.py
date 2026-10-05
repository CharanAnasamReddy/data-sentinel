from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ai_agent import AIInsight
from .deterministic_engine import TestResult


@dataclass
class DashboardPanel:
    title: str
    value: str
    detail: str = ""


class ExecutiveDashboard:
    """Business-facing view over deterministic validation and AI analysis."""

    def __init__(self) -> None:
        self.panels: list[DashboardPanel] = []

    def render(self, results: list[TestResult], ai_insights: dict[str, AIInsight]) -> dict[str, Any]:
        return self.build_summary(results, ai_insights)

    def build_summary(self, results: list[TestResult], ai_insights: dict[str, AIInsight]) -> dict[str, Any]:
        pass_count = sum(1 for result in results if result.status.value == "PASS")
        fail_count = sum(1 for result in results if result.status.value == "FAIL")
        warn_count = sum(1 for result in results if result.status.value == "WARN")

        self.panels = [
            DashboardPanel(title="Passed checks", value=str(pass_count), detail="Objective validations that succeeded."),
            DashboardPanel(title="Failed checks", value=str(fail_count), detail="Deterministic checks that failed."),
            DashboardPanel(title="Warnings", value=str(warn_count), detail="Manual review may be required."),
        ]

        summary = []
        for result in results:
            insight = ai_insights.get(result.test_id)
            if insight is None:
                summary.append({"test_id": result.test_id, "status": result.status.value, "summary": result.details})
            else:
                summary.append({
                    "test_id": result.test_id,
                    "status": result.status.value,
                    "summary": insight.summary,
                    "business_explanation": insight.business_explanation,
                })

        return {
            "panels": [panel.__dict__ for panel in self.panels],
            "summary": summary,
        }
