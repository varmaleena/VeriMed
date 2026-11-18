import "server-only";
import { headers } from "next/headers";
import { getToken } from "next-auth/jwt";
import { auth } from "../auth";
import { redirect } from "next/navigation";

import type { components } from "@verimed/api-client";
export type WorklistResult = components["schemas"]["EncounterPage"];

export async function readWorklist(status?: string): Promise<WorklistResult> {
  const session = await auth();
  if (!session?.user || session.user.expiresAt <= Date.now() / 1000)
    redirect("/login");
  const base = process.env.CELL_API_URL;
  if (!base) throw new Error("Encounter service is awaiting configuration.");
  const secureCookie =
    new URL(process.env.AUTH_URL ?? "http://localhost:3000").protocol ===
    "https:";
  const cookieName = secureCookie
    ? "__Secure-authjs.session-token"
    : "authjs.session-token";
  const token = await getToken({
    req: { headers: await headers() },
    secret: process.env.AUTH_SECRET,
    secureCookie,
    cookieName,
    salt: cookieName,
  });
  if (!token || typeof token.accessToken !== "string") redirect("/login");
  const url = new URL(base + "/encounters");
  if (status) url.searchParams.set("status", status);
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token.accessToken}` },
    cache: "no-store",
    signal: AbortSignal.timeout(28000),
  });
  if (response.status === 401) redirect("/login");
  if (response.status === 403)
    throw new Error("Your account does not have access to the Worklist.");
  if (!response.ok)
    throw new Error("The encounter service is unavailable. Try again shortly.");
  return (await response.json()) as WorklistResult;
}
