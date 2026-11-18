"use client";
export default function PatientsError({ reset }: { reset: () => void }) {
  return (
    <>
      <h1>Patients</h1>
      <section className="panel" role="alert">
        <h2>Patient records could not be loaded</h2>
        <p className="muted">
          Retry or ask your tenant administrator to check your access.
        </p>
        <button onClick={reset}>Try again</button>
      </section>
    </>
  );
}
