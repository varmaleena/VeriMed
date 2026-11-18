import { signOut } from "../../auth";
import { requireSession } from "../../lib/session";
import { ClinicalNavigation } from "./navigation";
export default async function ClinicalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await requireSession();
  const tenant = process.env.VERIMED_TENANT_NAME;
  if (!tenant) throw new Error("VERIMED_TENANT_NAME is required");
  return (
    <div className="shell">
      <a className="skip" href="#content">
        Skip to content
      </a>
      <header>
        <span className="brand">ChartVigil</span>
        <span className="tenant">{tenant}</span>
        <span className="identity">
          {session.user.name ?? "Hospital account"}
        </span>
        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/login" });
          }}
        >
          <button className="secondary">Sign out</button>
        </form>
      </header>
      <aside>
        <ClinicalNavigation />
        <p className="caption">
          HIPAA-aligned design,
          <br />
          synthetic data only
        </p>
      </aside>
      <main id="content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
