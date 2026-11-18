import { readWorklist } from "../../../lib/worklist";

const statuses = [
  "INGESTING",
  "READY_FOR_AUDIT",
  "AUDITING",
  "IN_REVIEW",
  "SIGNED",
  "FAILED",
];
function label(value: string) {
  return value.toLowerCase().replaceAll("_", " ");
}

export default async function Worklist({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const query = await searchParams;
  const status = statuses.includes(query.status ?? "")
    ? query.status
    : undefined;
  const result = await readWorklist(status);
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Worklist</h1>
          <p className="muted">Clinical notes awaiting review</p>
        </div>
        <form>
          <label htmlFor="status">Status</label>
          <select id="status" name="status" defaultValue={status ?? ""}>
            <option value="">All statuses</option>
            {statuses.map((item) => (
              <option value={item} key={item}>
                {label(item)}
              </option>
            ))}
          </select>
          <button className="secondary" type="submit">
            Apply
          </button>
        </form>
      </div>
      <section className="panel worklist-panel">
        {result.items.length === 0 ? (
          <div className="empty">
            <h2>No encounters in this view</h2>
            <p className="muted">
              Encounters will appear after they enter the cell through
              ingestion.
            </p>
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <caption className="sr-only">Encounter worklist</caption>
              <thead>
                <tr>
                  <th>Patient token</th>
                  <th>Birth year / sex</th>
                  <th>Encounter time</th>
                  <th>Scribe</th>
                  <th>Status</th>
                  <th>Assigned</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.patient_token}</td>
                    <td>
                      {item.birth_year ?? "—"} / {item.sex ?? "—"}
                    </td>
                    <td>
                      <time dateTime={item.started_at}>
                        {new Intl.DateTimeFormat("en-IN", {
                          dateStyle: "medium",
                          timeStyle: "short",
                          timeZone: "Asia/Kolkata",
                        }).format(new Date(item.started_at))}
                      </time>
                    </td>
                    <td>{item.scribe_adapter}</td>
                    <td>
                      <span className="status">{label(item.status)}</span>
                    </td>
                    <td className="mono">
                      {item.assigned_user_id ?? "Unassigned"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {result.has_more && (
          <p className="caption result-limit">
            Showing the most recent 50 encounters. Filter by status to narrow
            the view.
          </p>
        )}
      </section>
    </>
  );
}
