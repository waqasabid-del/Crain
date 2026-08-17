import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Comfortably above the 3s asyncUtilTimeout in vitest.setup.ts. When the two
    // are equal, a query that genuinely fails reports as "test timed out"
    // rather than naming the element it could not find.
    testTimeout: 15_000,
    setupFiles: ["./vitest.setup.ts"],
    // Bound the number of test files running at once.
    //
    // Unbounded, Vitest starts a worker per core and every one of them boots
    // jsdom, renders a full app shell and runs axe. On a busy machine the suite
    // then spends longer queued than working, and a `findBy` that would resolve
    // in 200ms exceeds `testTimeout` — so tests fail by timing out, a *different*
    // subset each run, with nothing wrong in the code they cover.
    //
    // That is worse than slow: a suite that fails randomly stops being read. It
    // gets re-run until green, which is the same as not having it. Four workers
    // leaves headroom for the machine and makes the result deterministic.
    maxWorkers: 4,
    minWorkers: 1,
    // Restore anything replaced with `vi.stubGlobal` after each test. Several
    // tests stub `fetch`; without this, one file's stub is still installed when
    // the next file runs, and the failure appears in whichever test happens to
    // run second rather than in the one that caused it.
    unstubGlobals: true,
    css: {
      // Process CSS Modules rather than stubbing them — same reasoning as
      // packages/ui/vitest.config.ts. Without `include`, Vitest hands every
      // component a proxy in which every property exists, so a test asserting
      // that a class was applied passes against a stylesheet that no longer
      // contains it.
      include: [/\.module\.css$/],
    },
    server: {
      deps: {
        // @cairn/ui and @cairn/api-client publish TypeScript source rather than
        // a build, and reach this app through a workspace symlink in
        // node_modules. Vitest externalises anything under node_modules by
        // default, which would hand raw .tsx and .module.css to Node's ESM
        // loader. Inlining them puts the workspace packages back through Vite's
        // transform, which is where they were always meant to go.
        inline: [/@cairn\//],
      },
    },
    coverage: {
      provider: "v8",
      // Measure the shipped source, not the repository.
      include: ["src/**"],
      // Coverage is a floor, never a target — md/17 §4.1
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
      exclude: ["**/*.test.*", "**/dist/**", "**/*.config.ts", "**/main.tsx"],
    },
  },
});
