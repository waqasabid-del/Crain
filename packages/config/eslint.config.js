import js from "@eslint/js";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier";
import jsxA11y from "eslint-plugin-jsx-a11y";

/**
 * Shared ESLint configuration.
 *
 * Accessibility rules are errors, not warnings — WCAG 2.1 AA is a locked
 * requirement (md/05-ux-design-privacy.md §A.6), so a violation must fail
 * the build rather than produce a warning nobody reads.
 */
export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/.next/**",
      "**/.open-next/**",
      "**/node_modules/**",
      "**/coverage/**",
      // Generated code is not hand-editable — a fix would be overwritten on the
      // next regeneration, leaving a permanently failing lint nobody can clear.
      // Style is the generator's responsibility; correctness is still enforced
      // because these files are type-checked like any other.
      "**/src/generated/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
      },
    },
    rules: {
      // Fail loudly — silent failures are the enemy (standards §8.2)
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/await-thenable": "error",

      // Explicit over clever (standards §8.1)
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/explicit-function-return-type": [
        "error",
        { allowExpressions: true, allowTypedFunctionExpressions: true },
      ],

      // Unused code is a liability — delete freely (standards §8.6)
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],

      // Console is not observability — use the logger
      "no-console": ["error", { allow: ["warn", "error"] }],
    },
  },
  {
    files: ["**/*.tsx"],
    ...jsxA11y.flatConfigs.strict,
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/tests/**"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
  prettier,
);
