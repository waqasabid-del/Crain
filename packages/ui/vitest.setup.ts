import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * Unmount between tests.
 *
 * Testing Library only auto-cleans when Vitest globals are enabled, and globals
 * are deliberately off here so that every import is explicit. Without this,
 * rendered components accumulate in the DOM and queries start matching elements
 * left over from earlier tests.
 */
afterEach(() => {
  cleanup();
});
