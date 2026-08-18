import { defineConfig, devices } from "@playwright/test";

import { API_ORIGIN, API_PORT, WEB_ORIGIN, WEB_PORT } from "./e2e/stack.js";

/**
 * The browser-level suite.
 *
 * Everything else in `apps/web` is jsdom with a mocked client: fast, and blind
 * to the half of the product that only exists in a browser — the session
 * cookie, the cross-origin call to the API, the redirect out of the auth gate,
 * the row-level security behind it. This config exists so exactly one test
 * exercises that path against the real stack.
 *
 * `.e2e.ts`, not `.spec.ts`: Vitest's default `include` matches `*.spec.ts`
 * anywhere in the package, and a Playwright file collected by Vitest fails in a
 * way that reads like a broken test rather than a misrouted one.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.e2e\.ts$/,

  // A test that only passes when it runs alone is a test that will fail in CI
  // for a reason nobody can reproduce. Declared rather than assumed.
  fullyParallel: false,
  workers: 1,

  // No retries anywhere. A retry turns a real intermittent product fault into a
  // green build, which is the failure mode this suite exists to prevent.
  retries: 0,

  // `test.only` left in a file makes the suite silently stop covering
  // everything else.
  forbidOnly: Boolean(process.env["CI"]),

  reporter: process.env["CI"] ? [["github"], ["list"]] : [["list"]],

  use: {
    baseURL: WEB_ORIGIN,
    // Kept only for the run that failed. An artefact for every green run is one
    // nobody looks at and everyone pays to store.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },

  // Chromium alone, deliberately. The audit gap is "nothing runs in a browser",
  // and closing it with one engine is honest; three would triple the runtime to
  // re-answer the same question about a single first-party app.
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  /*
   * Both halves of the stack, so `pnpm --filter @cairn/web e2e` works from
   * cold. The database is *not* started here — it holds the seed this test
   * reads, so bringing it up is `make db-up && make migrate && make seed`, and
   * a config that silently created an empty one would produce a confusing
   * failure instead of a clear one.
   */
  webServer: [
    {
      command: `uv run uvicorn --factory cairn_api.api:create_app --port ${String(API_PORT)}`,
      url: `${API_ORIGIN}/healthz`,
      cwd: "../..",
      // **Never reuse.** See the web server below: the same argument applies
      // here, and an API started by hand is one started with whatever backend,
      // database and CORS origins that shell happened to hold.
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        // See stack.ts: the offline default abstains, so the Brief would have
        // no claims and no citations to assert about.
        CAIRN_MODEL_BACKEND: "scripted",
        // JSON, not the comma-separated form the field's validator documents:
        // pydantic-settings parses a tuple-typed field as JSON at the source
        // level, before any `mode="before"` validator is reached.
        CAIRN_CORS_ALLOWED_ORIGINS: JSON.stringify([WEB_ORIGIN]),
        // The real sender, into the local sink. Not the console backend: a
        // message written to a log is a message nobody clicked, which is how a
        // verification link pointing at a route that did not exist survived.
        CAIRN_EMAIL_BACKEND: "smtp",
        CAIRN_SMTP_HOST: "localhost",
        CAIRN_SMTP_PORT: "1025",
        // The links in captured mail have to point at the app these tests
        // drive, not at the developer's own dev server on 3000.
        CAIRN_PUBLIC_APP_URL: WEB_ORIGIN,
      },
    },
    {
      /*
       * A production build, then serve it — not `next dev`.
       *
       * Dev mode compiles each route on its first request, at 60-120 seconds a
       * route on this codebase, billed to whichever test happens to touch the
       * route first. That made journeys fail on a timeout when run as a suite
       * and pass alone — the exact "flaky" shape that erodes trust in the whole
       * layer. One build up front costs about ninety seconds, is paid once, and
       * serves every route in milliseconds; it is also what a deployment runs,
       * where dev mode is a mode nothing else ever exercises.
       *
       * `NEXT_PUBLIC_*` is inlined at build time, so the env on this command is
       * the one that decides which API origin the browser calls.
       */
      command: `pnpm exec next build && pnpm exec next start --port ${String(WEB_PORT)}`,
      url: `${WEB_ORIGIN}/login`,
      /*
       * **Never reuse an existing server, locally or in CI.**
       *
       * This is the line that made the whole suite prove nothing. Next inlines
       * `NEXT_PUBLIC_*` into the bundle when it compiles, so the API origin the
       * browser calls is decided by the environment of whichever server is
       * running — and `reuseExistingServer` adopts any process already holding
       * the port without being able to see how it was started. A server started
       * by hand has no `NEXT_PUBLIC_API_URL`, so its bundle falls back to
       * `http://localhost:8000` from `src/env.ts`, every call leaves the origin
       * this suite serves from, and the API on that port refuses it: four
       * pre-existing specs failing with "CAIRN could not reach the server",
       * which reads like a product fault and is not one.
       *
       * Starting fresh costs about a minute locally. The alternative is a suite
       * that is fast, green, and pointed at a different API than the one under
       * test — and `CI` was the only thing standing between that and the build,
       * which is exactly the local/CI divergence this config is supposed to
       * prevent.
       *
       * A port already in use now fails loudly instead of being adopted
       * silently, which is the outcome to want.
       */
      reuseExistingServer: false,
      // A cold `next dev` compiles the route on first request, and the
      // readiness probe *is* that first request. Measured at ~54s to "Ready"
      // plus the compile on this machine, and 180s was not enough for both.
      timeout: 300_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_API_URL: API_ORIGIN,
        // Its own build directory, so this server cannot serve chunks that a
        // developer's own `pnpm dev` compiled with a different API origin baked
        // into them. See `next.config.ts`.
        NEXT_DIST_DIR: ".next-e2e",
      },
    },
  ],

  // Wide enough to absorb a cold route compile, narrow enough that a hung page
  // fails rather than occupying a CI runner for its whole timeout.
  timeout: 120_000,
  expect: { timeout: 20_000 },
});
