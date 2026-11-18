"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function ClinicalNavigation() {
  const pathname = usePathname();
  return (
    <nav aria-label="Clinical navigation">
      <Link
        href="/worklist"
        aria-current={pathname === "/worklist" ? "page" : undefined}
      >
        Worklist
      </Link>
      <Link
        href="/patients"
        aria-current={pathname === "/patients" ? "page" : undefined}
      >
        Patients
      </Link>
      <Link
        href="/settings"
        aria-current={pathname === "/settings" ? "page" : undefined}
      >
        Settings
      </Link>
    </nav>
  );
}
