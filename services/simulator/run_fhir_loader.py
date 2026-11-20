"""Run the real Synthea/HealthLake import workflow without logging clinical content."""

import argparse
import json
from pathlib import Path

import boto3  # type: ignore[import-untyped]
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from simulator.fhir_loader import check, inspect, submit
from simulator.fhir_schemas import ImportConfig, ImportState


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["submit", "check"])
    parser.add_argument("--profile", default="default")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--report", type=Path, default=Path("docs/fhir-import-verification.json")
    )
    args = parser.parse_args()
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    session = boto3.Session(profile_name=args.profile)
    if args.command == "submit":
        if args.source is None or args.config is None:
            parser.error("submit requires --source and --config")
        config = ImportConfig.model_validate_json(args.config.read_bytes())
        cohort = inspect(args.source)
        print(
            "Estimated incremental import spend: $"
            + format(config.estimated_usd, ".2f")
            + "; existing datastore window is unchanged."
        )
        state = submit(session, config, args.source, cohort)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(
            "Real HealthLake import submitted; state saved privately. Use check to verify completion."
        )
    else:
        state = ImportState.model_validate_json(args.state.read_bytes())
        report = check(session, state)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASSED" else 2
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:  # noqa: BLE001 -- Do not serialize record, credential, file-path or provider error bodies.
        print(
            "FHIR import failed; verify configuration, source integrity and AWS permissions. No clinical error payload logged."
        )
        code = 1
    raise SystemExit(code)
