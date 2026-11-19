import type { components } from "@verimed/api-client";
import { readCell } from "./cell-api";

export function readPatients(cursor?: string) {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  return readCell<components["schemas"]["PatientPage"]>("patients", params);
}

export async function readPatientSnapshot(cursor?: string) {
  const result = await readPatients(cursor);
  return { result, retrievedAt: new Date().toISOString() };
}
