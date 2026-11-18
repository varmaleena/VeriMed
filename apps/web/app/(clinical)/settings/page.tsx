import { readAppearance } from "../../../lib/appearance";
import { saveAppearance } from "./actions";
import { SaveAppearanceButton } from "./save-button";

export default async function Settings({
  searchParams,
}: {
  searchParams: Promise<{ saved?: string; invalid?: string }>;
}) {
  const appearance = await readAppearance();
  const params = await searchParams;
  return (
    <div className="settings-page">
      <div className="page-heading">
        <div>
          <h1>Settings</h1>
          <p className="muted">Make your workspace comfortable to review.</p>
        </div>
      </div>
      <section
        className="panel appearance-panel"
        aria-labelledby="appearance-heading"
      >
        <h2 id="appearance-heading">Appearance</h2>
        <p className="muted">Saved in this browser for this site.</p>
        <form action={saveAppearance}>
          <fieldset
            className="appearance-fieldset"
            aria-describedby="theme-help"
          >
            <legend>Theme</legend>
            <p className="caption" id="theme-help">
              Use your device setting or choose a fixed appearance.
            </p>
            <div className="appearance-choices">
              {(
                [
                  [
                    "system",
                    "System",
                    "Follow your device's light or dark mode.",
                  ],
                  ["light", "Light", "Light surfaces with dark text."],
                  ["dark", "Dark", "Dark surfaces with light text."],
                ] as const
              ).map(([value, label, description]) => (
                <label className="appearance-choice" key={value}>
                  <input
                    type="radio"
                    name="theme"
                    value={value}
                    defaultChecked={appearance.theme === value}
                  />
                  <span>
                    <strong>{label}</strong>
                    <span className="caption">{description}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset
            className="appearance-fieldset"
            aria-describedby="density-help"
          >
            <legend>Table density</legend>
            <p className="caption" id="density-help">
              Adjust spacing while keeping text readable.
            </p>
            <div
              className="appearance-choices density-choices"
              aria-describedby="density-help"
            >
              {(
                [
                  [
                    "comfortable",
                    "Comfortable",
                    "More space between patient and encounter rows.",
                  ],
                  ["compact", "Compact", "Fit more rows in your workspace."],
                ] as const
              ).map(([value, label, description]) => (
                <label className="appearance-choice" key={value}>
                  <input
                    type="radio"
                    name="density"
                    value={value}
                    defaultChecked={appearance.density === value}
                  />
                  <span>
                    <strong>{label}</strong>
                    <span className="caption">{description}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="appearance-save">
            <SaveAppearanceButton />
            {params.invalid === "1" ? (
              <p role="alert">Choose a theme and a density option.</p>
            ) : params.saved === "1" ? (
              <p role="status">Appearance saved.</p>
            ) : null}
          </div>
        </form>
      </section>
    </div>
  );
}
