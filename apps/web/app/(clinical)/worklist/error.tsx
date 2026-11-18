"use client";
export default function WorklistError({ reset }: { reset: () => void }) {
  return (
    <>
      <h1>Worklist</h1>
      <section className="panel" role="alert">
        <h2>Encounters could not be loaded</h2>
        <p className="muted">
          The service may be waking up or your account may need access. Retry,
          or ask your tenant administrator for help.
        </p>
        <button onClick={reset}>Try again</button>
      </section>
    </>
  );
}
