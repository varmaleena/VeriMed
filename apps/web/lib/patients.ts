import type { components } from "@verimed/api-client";
import { readCell } from "./cell-api";

export function readPatients(cursor?: string) {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  return readCell<components["schemas"]["PatientPage"]>("patients", params);
}
