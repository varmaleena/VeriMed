import type { components } from "@verimed/api-client";
import { readCell } from "./cell-api";

export function readWorklist(status?: string) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  return readCell<components["schemas"]["EncounterPage"]>("encounters", params);
}
