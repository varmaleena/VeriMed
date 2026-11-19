"""Apply the platform revisions to the configured dev cluster."""

import os

import boto3  # type: ignore[import-untyped]
import structlog
from app.migrations import apply
from botocore.config import Config  # type: ignore[import-untyped]
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

if __name__ == "__main__":
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    client = boto3.client(
        "rds-data",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 1}),
    )
    try:
        revisions = apply(
            client,
            {
                "resourceArn": os.environ["DATABASE_CLUSTER_ARN"],
                "secretArn": os.environ["DATABASE_SECRET_ARN"],
                "database": "verimed",
            },
        )
        print(
            "Platform schema current; applied revisions: "
            + (", ".join(revisions) or "none")
        )
    finally:
        client.close()
