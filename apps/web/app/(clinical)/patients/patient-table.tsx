"use client";

import { useState, useTransition } from "react";
import type { components } from "@verimed/api-client";
import { loadPatientPage } from "./actions";

type Page = components["schemas"]["PatientPage"];

export function PatientTable({ initialPage }: { initialPage: Page }) {
  const [page, setPage] = useState(initialPage);
  const [history, setHistory] = useState<{ cursor?: string; start: number }[]>([
    { start: 1 },
  ]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function navigate(direction: -1 | 1) {
    const targetIndex = index + direction;
    const target =
      direction === -1
        ? history[targetIndex]
        : {
            cursor: page.next_cursor ?? undefined,
            start: history[index].start + page.items.length,
          };
    if (!target || (direction === 1 && !page.next_cursor)) return;
    setError(null);
    startTransition(async () => {
      try {
        const result = await loadPatientPage(target.cursor);
        if ("unavailable" in result) {
          setError(
            result.expired
              ? "The patient testing window has ended."
              : "Patients could not be loaded. Try again.",
          );
          return;
        }
        setPage(result);
        if (direction === 1)
          setHistory([...history.slice(0, index + 1), target]);
        setIndex(targetIndex);
      } catch {
        setError(
          "Patients could not be loaded. Refresh the page to check your session and try again.",
        );
      }
    });
  }

  const first = page.items.length ? history[index].start : 0;
  const last = page.items.length ? first + page.items.length - 1 : 0;
  return (
    <section
      className="panel worklist-panel"
      aria-label="Patients"
      aria-busy={pending}
    >
      {page.items.length === 0 ? (
        <div className="empty">
          <h2>No patient records returned</h2>
          <p className="muted">
            The connected FHIR store has no patients in this view.
          </p>
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="sr-only">
              Synthetic patients from the live FHIR store
            </caption>
            <thead>
              <tr>
                <th scope="col">Patient token</th>
                <th scope="col">Birth year</th>
                <th scope="col">Sex</th>
                <th scope="col">FHIR record</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((patient) => (
                <tr key={patient.id}>
                  <td className="mono">{patient.display_token}</td>
                  <td>{patient.birth_year ?? "—"}</td>
                  <td>{patient.sex ?? "—"}</td>
                  <td className="mono">Patient/{patient.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
      {error && (
        <p className="pagination-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
