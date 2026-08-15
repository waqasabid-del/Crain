import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: {
      // `include` actually processes CSS Modules. Without it Vitest hands
      // components a proxy where every property exists, so a test asserting a
      // class passes against a stylesheet that no longer has it.
      // Leave `classNameStrategy` at "scoped": "non-scoped" and "stable" tell
      // Vitest to skip processing and return the proxy again.
      include: [/\.module\.css$/],
    },
    coverage: {
      provider: "v8",
      // Measure the shipped source, not build tooling no test imports.
      include: ["src/**"],
      // Coverage is a floor, never a target — md/17 §4.1
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
      exclude: ["**/*.test.*", "**/dist/**", "**/*.config.ts", "**/index.ts"],
    },
  },
});
