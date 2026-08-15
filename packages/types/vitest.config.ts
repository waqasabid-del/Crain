import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      // Measure the shipped source, not the repository. Without this, coverage
      // counts eslint.config.js and the codegen scripts — build tooling that no
      // test imports and none should — so the percentage describes the size of
      // the tooling rather than how well the product is tested.
      include: ["src/**"],
      // Coverage is a floor, never a target — md/17 §4.1
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
      exclude: [
        "**/*.test.ts",
        "**/dist/**",
        "**/*.config.ts",
        // Generated code, excluded for the same reason ESLint ignores it: its
        // correctness is the generator's responsibility, and it is verified by
        // the schema-drift check rather than by hand-written tests. Counting it
        // would mean either writing tests that assert a code generator emitted
        // what it emitted, or carrying a permanently failing threshold.
        "**/generated/**",
      ],
    },
  },
});
