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
    /*
     * Build tooling — ESLint's own config, Vitest config and setup, codegen
     * scripts.
     *
     * None of it is shipped, so none of it appears in a tsconfig `include`, and
     * the type-aware rules cannot parse a file outside the project graph: they
     * report "not found by the project service" instead of linting it. That
     * parse failure is why the package lint scripts were narrowed to `src` in
     * the first place — which quietly left every one of these files unchecked.
     *
     * Disabling type-aware rules for this subset is the right trade. These
     * files still get the syntactic rules (unused variables, no-console,
     * accidental globals), which is what actually goes wrong in build scripts,
     * and no tsconfig has to pretend that tooling is part of the product.
     */
    files: [
      "**/*.config.{js,mjs,ts}",
      "**/eslint.config.js",
      "**/vitest.setup.ts",
      "**/scripts/**/*.{js,mjs}",
    ],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: {
      // `disableTypeChecked` turns off the type-aware *rules*, but the parser
      // still consults the project service and fails before any rule runs.
      // Switching it off here is what actually makes these files lintable.
      parserOptions: { projectService: false, project: null },
      // These run under Node, not in a browser or a Worker.
      globals: { console: "readonly", process: "readonly", URL: "readonly" },
    },
    rules: {
      ...tseslint.configs.disableTypeChecked.rules,
      // `no-console` exists because console is not observability — but a
      // codegen script's output *is* its user interface. Telling a developer
      // which files were written belongs on stdout, not in a structured logger
      // that nothing collects at build time.
      "no-console": "off",
    },
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "**/tests/**"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
  prettier,
);
