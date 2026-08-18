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
      reuseExistingServer: !process.env["CI"],
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
      command: `pnpm exec next dev --port ${String(WEB_PORT)}`,
      url: `${WEB_ORIGIN}/login`,
      reuseExistingServer: !process.env["CI"],
      // Generous: the first request to a route compiles it.
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_API_URL: API_ORIGIN,
      },
    },
  ],

  // Wide enough to absorb a cold route compile, narrow enough that a hung page
  // fails rather than occupying a CI runner for its whole timeout.
  timeout: 120_000,
  expect: { timeout: 20_000 },
});
