import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    coverage: {
      provider: "v8",
      // Coverage is a floor, never a target — md/17 §4.1
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
      exclude: ["**/*.test.*", "**/dist/**", "**/*.config.ts", "**/index.ts"],
    },
  },
});
