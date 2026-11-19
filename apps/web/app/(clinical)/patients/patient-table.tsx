"use client";

import { useRef, useState, useTransition } from "react";
import type { components } from "@verimed/api-client";
import { loadPatientPage } from "./actions";

type Page = components["schemas"]["PatientPage"];
type PageLocation = { cursor?: string; start: number };

const retrievalTime = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "Asia/Kolkata",
});

function sexLabel(value: string | null | undefined) {
  if (!value) return "Not recorded";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function PatientTable({
  initialPage,
  initialRetrievedAt,
}: {
  initialPage: Page;
  initialRetrievedAt: string;
}) {
  const [page, setPage] = useState(initialPage);
  const [retrievedAt, setRetrievedAt] = useState(initialRetrievedAt);
  const [history, setHistory] = useState<PageLocation[]>([{ start: 1 }]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<"page" | "refresh">(
    "page",
  );
  const [pending, startTransition] = useTransition();
  const inFlight = useRef(false);

  function navigate(direction: -1 | 0 | 1) {
    if (inFlight.current) return;
    const targetIndex = direction === 0 ? 0 : index + direction;
    const target: PageLocation | undefined =
      direction === 0
        ? { start: 1 }
        : direction === -1
          ? history[targetIndex]
          : {
              cursor: page.next_cursor ?? undefined,
              start: history[index].start + page.items.length,
            };
    if (!target || (direction === 1 && !page.next_cursor)) return;
    inFlight.current = true;
    setError(null);
    setPendingAction(direction === 0 ? "refresh" : "page");
    startTransition(async () => {
      try {
        const snapshot = await loadPatientPage(target.cursor);
        const result = snapshot.result;
        if ("unavailable" in result) {
          setError(
            result.expired
              ? "The testing window has ended. These are previously retrieved results."
              : "Patients could not be loaded. Showing the previously retrieved results; try again.",
          );
          return;
        }
        setPage(result);
        setRetrievedAt(snapshot.retrievedAt);
        if (direction === 0) setHistory([{ start: 1 }]);
        else if (direction === 1)
          setHistory([...history.slice(0, index + 1), target]);
        setIndex(targetIndex);
      } catch {
        setError(
          "Patients could not be loaded. Showing previous results. Refresh the browser to check your session and try again.",
        );
      } finally {
        inFlight.current = false;
      }
    });
  }

  const first = page.items.length ? history[index].start : 0;
  const last = page.items.length ? first + page.items.length - 1 : 0;
  return (
    <section
      className="panel worklist-panel patient-directory"
      aria-labelledby="patient-directory-heading"
    >
      <div className="patient-toolbar">
        <div>
          <h2 id="patient-directory-heading">Patient records</h2>
          <p className="caption" id="patient-retrieval-status">
            {error ? "Showing previous results" : "Retrieved"} ·{" "}
            <time
              dateTime={retrievedAt}
              title={new Date(retrievedAt).toISOString()}
            >
              {retrievalTime.format(new Date(retrievedAt))} IST
            </time>
          </p>
        </div>
        <button
          type="button"
          className="secondary"
          disabled={pending}
          title="Reload patients and return to the first page"
          onClick={() => navigate(0)}
        >
          <span aria-hidden="true">↻ </span>
          {pending && pendingAction === "refresh"
            ? "Refreshing…"
            : "Refresh list"}
        </button>
      </div>
      {error && (
        <div className="patient-read-error" role="alert">
          {error}
        </div>
      )}
      <div aria-busy={pending} aria-describedby="patient-retrieval-status">
        {page.items.length === 0 ? (
          <div className="empty">
            <h2>No patient records returned</h2>
            <p className="muted">
              The connected FHIR store has no patients in this view.
            </p>
          </div>
        ) : (
          <div
            className="table-scroll patient-table-scroll"
            role="region"
            aria-label="Patient records table"
            tabIndex={0}
          >
            <table>
              <caption className="sr-only">
                Synthetic patients from the live FHIR store. Source identifiers
                can be expanded for each patient.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Patient token</th>
                  <th scope="col">Birth year</th>
                  <th scope="col">Sex</th>
                  <th scope="col">Source record</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((patient) => (
                  <tr key={patient.id}>
                    <th scope="row" className="patient-token">
                      <span className="mono">{patient.display_token}</span>
                    </th>
                    <td>
                      {patient.birth_year ?? (
                        <span className="muted">Not recorded</span>
                      )}
                    </td>
                    <td>{sexLabel(patient.sex)}</td>
                    <td>
                      <details className="record-details">
                        <summary>
                          View FHIR ID
                          <span className="sr-only">
                            {" "}
                            for {patient.display_token}
                          </span>
                        </summary>
                        <code>Patient/{patient.id}</code>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <nav className="patient-pagination" aria-label="Patient pagination">
        <span className="caption">20 patients per page</span>
        <div className="pagination-controls">
          <button
            type="button"
            aria-label="Previous patients"
            disabled={pending || index === 0}
            onClick={() => navigate(-1)}
          >
            ‹
          </button>
          <span className="pagination-range" role="status" aria-live="polite">
            {pending
              ? "Loading…"
              : `${first}–${last}${page.total != null ? ` of ${page.total}` : ""}`}
          </span>
          <button
            type="button"
            aria-label="Next patients"
            disabled={pending || !page.next_cursor}
            onClick={() => navigate(1)}
          >
            ›
          </button>
        </div>
      </nav>
    </section>
  );
}
