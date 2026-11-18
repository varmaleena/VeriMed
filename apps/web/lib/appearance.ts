import "server-only";
import { cookies } from "next/headers";

export type Theme = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

export function isTheme(value: unknown): value is Theme {
  return value === "system" || value === "light" || value === "dark";
}

export function isDensity(value: unknown): value is Density {
  return value === "comfortable" || value === "compact";
}

export async function readAppearance(): Promise<{
  theme: Theme;
  density: Density;
}> {
  const store = await cookies();
  const theme = store.get("chartvigil-theme")?.value;
  const density = store.get("chartvigil-density")?.value;
  return {
    theme: isTheme(theme) ? theme : "system",
    density: isDensity(density) ? density : "comfortable",
  };
}
