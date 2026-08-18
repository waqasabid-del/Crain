import { existsSync } from "node:fs";
import { resolve } from "node:path";

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { VerifyPage } from "./VerifyPage.js";

/**
 * **The screen the verification email has always linked to, and which did not
 * exist.**
 *
 * Every account created since signup shipped received a message pointing at
 * `{CAIRN_PUBLIC_APP_URL}/verify?token=...`. There was no `/verify` route, no
 * `verifyEmail` on the API client, and nothing in the web app that called
 * `POST /v1/auth/verify-email` at all. The link returned 404.
 *
 * Nothing detected it. The API's own tests covered the endpoint and passed; the
 * message builder's tests asserted the link was in the body and passed; the
 * console email backend printed the link to a log where nobody clicked it. The
 * defect lived exactly in the gap between two things that each worked.
 *
 * That is why local development now sends through a real SMTP sink: a link in a
 * log line and a link that resolves are indistinguishable until somebody clicks
 * one.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

describe("verifying an email address", () => {
  it("redeems the token in the link without being asked to do anything", async () => {
    // The reader has already proved control of the inbox by opening the link.
    // Asking them to press a button afterwards adds a step that proves nothing.
    const verifyEmail = vi.fn(() => Promise.resolve(SESSION));
    renderRoute(<VerifyPage />, {
      client: createStubClient({ verifyEmail }),
      route: "/verify",
      search: "token=a-real-token",
    });

    expect(await screen.findByRole("heading", { name: /address is confirmed/i })).toBeVisible();
    expect(verifyEmail).toHaveBeenCalledWith({ token: "a-real-token" });
  });

  it("sends a confirmed reader onward rather than leaving them on a dead end", async () => {
    renderRoute(<VerifyPage />, {
      client: createStubClient({ verifyEmail: vi.fn(() => Promise.resolve(SESSION)) }),
      route: "/verify",
      search: "token=a-real-token",
    });

    await screen.findByRole("heading", { name: /address is confirmed/i });
    expect(screen.getByRole("link", { name: /continue/i })).toHaveAttribute("href", "/");
  });

  it("says what to do when the link has already been used", async () => {
    // A 409 covers unknown, expired, already-used and superseded, deliberately:
    // distinguishing them would confirm account state to whoever holds the link.
    // The reader still needs one clear action.
    renderRoute(<VerifyPage />, {
      client: createStubClient({
        verifyEmail: vi.fn(() => Promise.reject(apiError(409, "Link no longer valid"))),
      }),
      route: "/verify",
      search: "token=stale",
    });

    expect(await screen.findByRole("heading", { name: /link did not work/i })).toBeVisible();
    expect(screen.getByText(/sign in and ask for a new one/i)).toBeVisible();
  });

  it("does not call the API when the link arrived without a token", async () => {
    // Email clients break long URLs. Calling with an empty token would spend a
    // request to be told what is already known.
    const verifyEmail = vi.fn(() => Promise.resolve(SESSION));
    renderRoute(<VerifyPage />, {
      client: createStubClient({ verifyEmail }),
      route: "/verify",
      search: "",
    });

    expect(await screen.findByRole("heading", { name: /link is incomplete/i })).toBeVisible();
    expect(verifyEmail).not.toHaveBeenCalled();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderRoute(<VerifyPage />, {
      client: createStubClient({ verifyEmail: vi.fn(() => Promise.resolve(SESSION)) }),
      route: "/verify",
      search: "token=a-real-token",
    });

    await screen.findByRole("heading", { name: /address is confirmed/i });
    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("is served at the exact path the verification email builds", () => {
    // The assertion that would have caught the original defect, and the only
    // one that spans the boundary it fell through: the API writes the link and
    // this app serves it, and neither side's tests can see the other.
    //
    // `apps/api/src/cairn_api/email/message.py` builds `/verify?token=`. If this
    // file moves or is deleted, every verification email in every inbox becomes
    // a 404 again, and nothing else in either test suite would fail.
    // `process.cwd()` is the workspace root under vitest; `import.meta.url` is
    // not a file URL here because the module is transformed in memory.
    expect(existsSync(resolve(process.cwd(), "src/app/verify/page.tsx"))).toBe(true);
  });
});
