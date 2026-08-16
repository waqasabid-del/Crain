import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library waits 1s by default, which these screens exceed: each renders
// a provider tree and several async reads. Raised to 8s after a full-suite run
// failed a different test on each pass at ~3s, always passing in isolation.
// Comfortably below vitest's 15s testTimeout, so a genuine failure still names
// the element it could not find rather than reporting a timeout.
configure({ asyncUtilTimeout: 8_000 });

/**
 * Unmount between tests, and reset the two pieces of global state this app
 * writes to.
 *
 * Testing Library only auto-cleans when Vitest globals are enabled, and globals
 * are deliberately off here so that every import is explicit.
 *
 * The theme is stored on `<html>` and in localStorage, both of which outlive a
 * render. Without the reset below, a test that selects the dark theme leaves it
 * selected for every test that runs after it — and the failure surfaces in an
 * unrelated file, which is the most expensive kind of test coupling to diagnose.
 */
afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

import { vi } from "vitest";

// Registered here rather than in a helper: `vi.mock` is hoisted to the top of
// the file that calls it, so a mock declared inside `test/harness.tsx` applied
// only to files that happened to import it first. One registration, before
// every suite.
vi.mock("next/navigation", async () => {
  const { navigationMock } = await import("./src/test/router-mock.js");
  return navigationMock;
});

import * as axeMatchers from "vitest-axe/matchers";
import { expect } from "vitest";

// Extended here rather than in the one suite that uses it, so the matcher's
// types are visible to TypeScript everywhere. `expect.extend` in a test file
// registers the matcher at runtime and tells the compiler nothing.
expect.extend(axeMatchers);

// Declaration merging, so `toHaveNoViolations` is visible to the compiler and
// not only registered at runtime. `expect.extend` in a test file does the
// second and not the first, which is why the audit suite failed to typecheck
// while passing.
//
// The rule against empty interfaces is disabled for exactly these two lines:
// an interface that only *extends* is the entire mechanism of declaration
// merging, and the rule cannot distinguish that from an accidental alias.
/* eslint-disable @typescript-eslint/no-empty-object-type */
declare module "vitest" {
  interface Assertion extends axeMatchers.AxeMatchers {}
  interface AsymmetricMatchersContaining extends axeMatchers.AxeMatchers {}
}
/* eslint-enable @typescript-eslint/no-empty-object-type */
