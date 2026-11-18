import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  globalIgnores([
    "**/node_modules/**",
    "**/.next/**",
    "**/dist/**",
    "**/cdk.out/**",
    ".phase*/**",
    ".venv*/**",
    "**/next-env.d.ts",
    "packages/api-client/schema.d.ts",
  ]),
  ...nextTypescript,
  {
    files: ["apps/web/**/*.{js,jsx,mjs,cjs,ts,tsx}"],
    extends: [nextVitals],
    settings: { next: { rootDir: "apps/web/" } },
  },
]);
