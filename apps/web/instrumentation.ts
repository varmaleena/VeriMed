export async function register() {
  if (
    process.env.NEXT_RUNTIME === "nodejs" &&
    process.env.VERIMED_HOSTED_WEB === "true"
  ) {
    const { loadHostedIdentity } = await import("./lib/hosted-identity");
    await loadHostedIdentity();
  }
}
