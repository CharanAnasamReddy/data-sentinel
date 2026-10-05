from __future__ import annotations

import argparse
import json

from .ai_agent import AIAgent
from .deterministic_engine import DeterministicTestingEngine
from .events import EventStore
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


def main() -> None:
    parser = argparse.ArgumentParser(description="data-sentinel deterministic ETL testing engine")
    parser.add_argument("--example", action="store_true", help="Run a sample validation cycle")
    args = parser.parse_args()

    if args.example:
        print(json.dumps(run_example(), indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
