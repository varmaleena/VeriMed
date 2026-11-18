"use client";

import { useFormStatus } from "react-dom";

export function SaveAppearanceButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending}>
      {pending ? "Saving…" : "Save preferences"}
    </button>
  );
}
