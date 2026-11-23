import "server-only";
import { context, propagation, ROOT_CONTEXT, trace } from "@opentelemetry/api";
import {
  NodeTracerProvider,
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
  SimpleSpanProcessor,
  type SpanExporter,
  type ReadableSpan,
} from "@opentelemetry/sdk-trace-node";
import {
  ExportResultCode,
  W3CTraceContextPropagator,
  type ExportResult,
} from "@opentelemetry/core";
import { PutTraceSegmentsCommand, XRayClient } from "@aws-sdk/client-xray";
import { traceDocument } from "./trace-document";

let provider: NodeTracerProvider | undefined;

class OperationalExporter implements SpanExporter {
  private readonly client = new XRayClient({
    region: process.env.AWS_REGION,
    maxAttempts: 1,
  });
  export(spans: ReadableSpan[], done: (result: ExportResult) => void): void {
    const documents = spans
      .map(traceDocument)
      .filter((value) => value !== null);
    if (!documents.length) {
      done({ code: ExportResultCode.SUCCESS });
      return;
    }
    this.client
      .send(
        new PutTraceSegmentsCommand({
          TraceSegmentDocuments: documents.map((value) =>
            JSON.stringify(value),
          ),
        }),
        { abortSignal: AbortSignal.timeout(1200) },
      )
      .then((result) => {
        if (result.UnprocessedTraceSegments?.length)
          throw new Error("TRACE_REJECTED");
        done({ code: ExportResultCode.SUCCESS });
      })
      .catch(() => {
        console.error("TRACE_EXPORT_FAILED");
        done({ code: ExportResultCode.FAILED });
      });
  }
  async shutdown(): Promise<void> {
    this.client.destroy();
  }
}

export function configureWebTracing(): void {
  if (provider || process.env.VERIMED_HOSTED_WEB !== "true") return;
  provider = new NodeTracerProvider({
    sampler: new ParentBasedSampler({
      root: new TraceIdRatioBasedSampler(0.05),
    }),
    spanProcessors: [new SimpleSpanProcessor(new OperationalExporter())],
    forceFlushTimeoutMillis: 1500,
  });
  provider.register({ propagator: new W3CTraceContextPropagator() });
}

export function startCellRead(incoming: string | null) {
  const parent =
    incoming && /^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$/.test(incoming)
      ? propagation.extract(ROOT_CONTEXT, { traceparent: incoming })
      : context.active();
  const span = trace
    .getTracer("chartvigil.web")
    .startSpan("web.cell.read", {}, parent);
  const carrier: Record<string, string> = {};
  propagation.inject(
    trace.setSpanContext(ROOT_CONTEXT, span.spanContext()),
    carrier,
  );
  return { span, traceparent: carrier.traceparent };
}

export async function flushWebTracing(): Promise<void> {
  try {
    await provider?.forceFlush();
  } catch {
    console.error("TRACE_EXPORT_FAILED");
  }
}
