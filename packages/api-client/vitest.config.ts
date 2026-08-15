import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      // Measure the shipped source, not the repository.
      include: ["src/**"],
      // Coverage is a floor, never a target — md/17 §4.1
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
      exclude: [
        "**/*.test.ts",
        "**/dist/**",
        "**/*.config.ts",
        // Generated code — verified by the drift test, not by hand-written tests.
        "**/generated/**",
      ],
    },
  },
});
