"use server";

import { readPatients } from "../../../lib/patients";

export async function loadPatientPage(cursor?: string) {
  if (cursor && cursor.length > 8192) throw new Error("Invalid patient page.");
  return readPatients(cursor);
}
