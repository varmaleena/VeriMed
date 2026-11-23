// Native Lambda Web Function entry point; no event-to-HTTP adapter.
const endpoint = process.env.AWS_LAMBDA_HTTP_ENDPOINT;
if (!endpoint || !/^[a-zA-Z0-9.:[\]-]+:\d+$/.test(endpoint))
  throw new Error("WEB_LISTEN_ADDRESS_REQUIRED");
const separator = endpoint.lastIndexOf(":");
process.env.HOSTNAME = endpoint.slice(0, separator);
process.env.PORT = endpoint.slice(separator + 1);
process.env.NODE_ENV = "production";
// Framework exceptions can contain clinical URLs. Keep operational categories only.
for (const level of ["log", "info", "warn", "error", "debug"]) {
  const write = console[level].bind(console);
  console[level] = (...args) => {
    if (args[0] === "TRACE_EXPORT_FAILED") {
      write(
        JSON.stringify({
          event: "web_trace_export_failed",
          error_code: "TRACE_EXPORT_FAILED",
          TraceExportFailures: 1,
          _aws: {
            Timestamp: Date.now(),
            CloudWatchMetrics: [
              {
                Namespace: "VeriMed",
                Dimensions: [[]],
                Metrics: [{ Name: "TraceExportFailures", Unit: "Count" }],
              },
            ],
          },
        }),
      );
    } else write(JSON.stringify({ event: "web_runtime", level }));
  };
}
import("./apps/web/server.js").catch(() => {
  console.error();
  process.exitCode = 1;
});
