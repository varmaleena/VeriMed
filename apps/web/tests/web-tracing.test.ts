import { test } from "node:test";
import { deepEqual, equal, ok } from "node:assert/strict";
import type { ReadableSpan } from "@opentelemetry/sdk-trace-node";
import { traceDocument } from "../lib/trace-document";

function input(changes: Record<string, unknown> = {}): ReadableSpan {
  return {
    name: "web.cell.read",
    spanContext: () => ({
      traceId: "1234567890abcdef1234567890abcdef",
      spanId: "1234567890abcdef",
      traceFlags: 1,
      traceState: { serialize: () => "unit-private-marker" },
    }),
    parentSpanContext: { spanId: "abcdef1234567890" },
    startTime: [100, 500000000],
    endTime: [101, 0],
    attributes: {
      "http.response.status_code": 200,
      patient: "unit-private-marker",
      authorization: "unit-private-marker",
    },
    status: { code: 2, message: "unit-private-marker" },
    events: [{ name: "unit-private-marker" }],
    links: [{ attributes: { patient: "unit-private-marker" } }],
    get resource() {
      throw new Error("Exporter must never read untrusted resources");
    },
    ...changes,
  } as unknown as ReadableSpan;
}

test("Web trace conversion exports only the fixed operational projection", () => {
  const result = traceDocument(input());
  deepEqual(result, {
    name: "web.cell.read",
    id: "1234567890abcdef",
    trace_id: "1-12345678-90abcdef1234567890abcdef",
    start_time: 100.5,
    end_time: 101,
    parent_id: "abcdef1234567890",
    http: { response: { status: 200 } },
    fault: true,
  });
  ok(!JSON.stringify(result).includes("unit-private-marker"));
});

test("Unexpected span names, invalid IDs and invalid timing are dropped", () => {
  equal(
    traceDocument(input({ name: "GET /patients/private-identifier" })),
    null,
  );
  equal(
    traceDocument(
      input({
        spanContext: () => ({
          traceId: "0".repeat(32),
          spanId: "1".repeat(16),
        }),
      }),
    ),
    null,
  );
  equal(traceDocument(input({ endTime: [99, 0] })), null);
  equal(traceDocument(input({ startTime: [Infinity, 0] })), null);
});

test("Unbounded and nonnumeric HTTP attributes are omitted", () => {
  for (const value of [
    "unit-private-marker",
    NaN,
    Infinity,
    true,
    999,
    200.1,
  ]) {
    const result = traceDocument(
      input({ attributes: { "http.response.status_code": value } }),
    );
    ok(result && !("http" in result));
  }
});
