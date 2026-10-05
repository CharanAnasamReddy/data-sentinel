from __future__ import annotations

import argparse
import json

from .ai_agent import AIAgent
from .deterministic_engine import DeterministicTestingEngine
from .events import EventStore
from .mappings import load_mapping_document
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
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--example", action="store_true", help="Run a sample validation cycle")
    commands.add_argument(
        "--validate-mapping",
        metavar="PATH",
        help="Validate a JSON, YAML, CSV, or Excel mapping document and show generated rules",
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

    parser.print_help()


if __name__ == "__main__":
    main()
