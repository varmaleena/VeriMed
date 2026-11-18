import { PatientTable } from "./patient-table";
import { readPatients } from "../../../lib/patients";

export default async function Patients() {
  const result = await readPatients();
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
      <PatientTable initialPage={result} />
    </>
  );
}
