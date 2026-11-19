"use server";

import { readPatientSnapshot } from "../../../lib/patients";
import { requireSession } from "../../../lib/session";

export async function loadPatientPage(cursor?: string) {
  await requireSession();
  if (
    cursor !== undefined &&
    (typeof cursor !== "string" || cursor.length > 8192)
  )
    throw new Error("Invalid patient page.");
  return readPatientSnapshot(cursor);
}
