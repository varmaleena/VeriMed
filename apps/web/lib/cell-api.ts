import "server-only";
import { headers } from "next/headers";
import { getToken } from "next-auth/jwt";
import { requireSession } from "./session";
import { redirect } from "next/navigation";

export interface Unavailable {
  unavailable: true;
  expired?: true;
}

export async function readCell<T>(
  resource: "encounters" | "patients",
  params: URLSearchParams,
): Promise<T | Unavailable> {
  await requireSession();
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
  const url = new URL(base + "/" + resource);
  url.search = params.toString();
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token.accessToken}` },
    cache: "no-store",
    signal: AbortSignal.timeout(28000),
  }).catch(() => null);
  if (!response) return { unavailable: true };
  if (response.status === 401) redirect("/login");
  if (response.status === 403)
    throw new Error("Your account does not have access to this clinical data.");
  if (response.status === 410) return { unavailable: true, expired: true };
  if (!response.ok) return { unavailable: true };
  try {
    return (await response.json()) as T;
  } catch {
    return { unavailable: true };
  }
}
