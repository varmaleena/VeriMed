import Link from "next/link";
import { readPatients } from "../../../lib/patients";

export default async function Patients({
  searchParams,
}: {
  searchParams: Promise<{ cursor?: string }>;
}) {
  const { cursor } = await searchParams;
  const result = await readPatients(cursor);
  if ("unavailable" in result)
    return (
      <>
        <h1>Patients</h1>
        <section className="panel" role="status">
          <h2>
            {result.expired
              ? "The synthetic-data test window has ended"
              : "The FHIR service is temporarily unavailable"}
          </h2>
          <p className="muted">
            {result.expired
              ? "The demo store can be recreated for the next testing or recording window."
              : "Try again shortly while the synthetic-data service becomes available."}
          </p>
          {!result.expired && (
            <form action="/patients">
              <button type="submit">Try again</button>
            </form>
          )}
        </section>
      </>
    );
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Patients</h1>
          <p className="muted">Live synthetic FHIR records</p>
        </div>
        {cursor && <Link href="/patients">First page</Link>}
      </div>
      <p className="caption">
        {result.source} · Testing window ends{" "}
        {new Intl.DateTimeFormat("en-IN", {
          dateStyle: "medium",
          timeStyle: "short",
          timeZone: "Asia/Kolkata",
        }).format(new Date(result.expires_at))}{" "}
        IST
      </p>
      <section className="panel worklist-panel">
        {result.items.length === 0 ? (
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
                  <th>Patient token</th>
                  <th>Birth year</th>
                  <th>Sex</th>
                  <th>FHIR record</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((patient) => (
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
      </section>
      <div className="pagination">
        <p className="caption">
          {result.items.length} records in this page
          {result.total != null
            ? ` · ${result.total} patients in the FHIR search`
            : ""}
        </p>
        {result.next_cursor && (
          <Link
            href={
              "/patients?" + new URLSearchParams({ cursor: result.next_cursor })
            }
          >
            Next patients →
          </Link>
        )}
      </div>
    </>
  );
}
