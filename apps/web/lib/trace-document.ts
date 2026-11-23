import type { ReadableSpan } from "@opentelemetry/sdk-trace-node";

/** Rebuild from operational fields only; never serialize the SDK span itself. */
export function traceDocument(
  span: ReadableSpan,
): Record<string, unknown> | null {
  const { traceId, spanId } = span.spanContext();
  if (
    span.name !== "web.cell.read" ||
    !/^[0-9a-f]{32}$/.test(traceId) ||
    /^0+$/.test(traceId) ||
    !/^[0-9a-f]{16}$/.test(spanId) ||
    /^0+$/.test(spanId)
  )
    return null;
  const start = span.startTime[0] + span.startTime[1] / 1e9;
  const end = span.endTime[0] + span.endTime[1] / 1e9;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start)
    return null;
  const document: Record<string, unknown> = {
    name: "web.cell.read",
    id: spanId,
    trace_id: `1-${traceId.slice(0, 8)}-${traceId.slice(8)}`,
    start_time: start,
    end_time: end,
  };
  const parent = span.parentSpanContext?.spanId;
  if (parent && /^[0-9a-f]{16}$/.test(parent) && !/^0+$/.test(parent))
    document.parent_id = parent;
  const status = span.attributes["http.response.status_code"];
  if (
    typeof status === "number" &&
    Number.isInteger(status) &&
    status >= 100 &&
    status <= 599
  )
    document.http = { response: { status } };
  if (span.status.code === 2) document.fault = true;
  return document;
}
