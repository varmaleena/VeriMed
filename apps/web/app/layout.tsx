import type { Metadata } from "next";
import "./globals.css";
import { readAppearance } from "../lib/appearance";
export const metadata: Metadata = {
  title: "ChartVigil",
  description: "Clinical note verification",
};
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { theme, density } = await readAppearance();
  return (
    <html lang="en" data-theme={theme} data-density={density}>
      <body>{children}</body>
    </html>
  );
}
