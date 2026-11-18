"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { requireSession } from "../../../lib/session";
import { isDensity, isTheme } from "../../../lib/appearance";

export async function saveAppearance(data: FormData) {
  await requireSession();

  const theme = data.get("theme");
  const density = data.get("density");
  if (
    !isTheme(theme) ||
    !isDensity(density) ||
    data.getAll("theme").length !== 1 ||
    data.getAll("density").length !== 1
  )
    redirect("/settings?invalid=1");

  const store = await cookies();
  const options = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.AUTH_URL
      ? new URL(process.env.AUTH_URL).protocol === "https:"
      : process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  };
  store.set("chartvigil-theme", theme, options);
  store.set("chartvigil-density", density, options);
  redirect("/settings?saved=1");
}
