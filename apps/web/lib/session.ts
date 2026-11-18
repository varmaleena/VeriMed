import "server-only";
import { redirect } from "next/navigation";
import { auth } from "../auth";

export async function requireSession() {
  const session = await auth();
  if (
    !session?.user ||
    !Number.isFinite(session.user.expiresAt) ||
    session.user.expiresAt <= Date.now() / 1000
  )
    redirect("/login");
  return session;
}
