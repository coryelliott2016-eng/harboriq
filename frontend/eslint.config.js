import js from "@eslint/js";
import globals from "globals";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage"] },
  {
    // jsx-a11y's own flat-config preset declares ESLint <=9 as a peer; it is
    // wired in manually here (plugin + spread rules) rather than via its
    // `flatConfigs.recommended` extend helper because that helper hard-fails
    // fast on ESLint 10's stricter API in this repo's toolchain. The rules
    // object itself (checked against the plugin's published recommended
    // config below) is plain data with no ESLint-version-specific API calls,
    // and manually running the linter against known a11y violations (missing
    // alt text, non-interactive click handlers, etc.) confirms it flags them
    // correctly under ESLint 10 -- see the audit note in .env.example/
    // frontend.md history. Bump this to the extend-based form once jsx-a11y
    // ships an ESLint 10 peer range.
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "jsx-a11y": jsxA11y,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...jsxA11y.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
);
