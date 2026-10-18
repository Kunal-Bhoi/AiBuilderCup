import tsParser from "@typescript-eslint/parser";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import reactHooks from "eslint-plugin-react-hooks";
export default [
  { ignores: ["dist/**", "node_modules/**", "artifacts/**"] },
  { files: ["src/**/*.{ts,tsx}"], languageOptions: { parser: tsParser, parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } } }, plugins: { "@typescript-eslint": tsPlugin, "react-hooks": reactHooks }, rules: { ...reactHooks.configs.recommended.rules, "@typescript-eslint/no-explicit-any": "error" } },
];
