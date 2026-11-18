export default function Worklist() {
  return (
    <>
      <h1>Worklist</h1>
      <section className="panel" aria-labelledby="status-heading">
        <h2 id="status-heading">Encounter service awaiting connection</h2>
        <p className="muted">
          Encounter records will appear here when the cell API is connected.
        </p>
      </section>
    </>
  );
}
