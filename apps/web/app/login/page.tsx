import { signIn } from "../../auth";
export const dynamic = "force-dynamic";
export default function Login() {
  const configured = Boolean(
    process.env.AUTH_COGNITO_ID &&
    process.env.AUTH_COGNITO_SECRET &&
    process.env.AUTH_COGNITO_ISSUER &&
    process.env.AUTH_SECRET,
  );
  return (
    <main className="login">
      <section className="login-panel">
        <p className="brand">ChartVigil</p>
        <h1>Clinical note verification</h1>
        <p className="muted">Sign in to your hospital workspace.</p>
        {configured ? (
          <form
            action={async () => {
              "use server";
              await signIn("cognito", { redirectTo: "/worklist" });
            }}
          >
            <button type="submit">Sign in with your hospital account</button>
          </form>
        ) : (
          <p role="status">Hospital sign-in is awaiting configuration.</p>
        )}
        <p className="caption">HIPAA-aligned design, synthetic data only</p>
      </section>
    </main>
  );
}
