import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { apiError, createStubClient, renderRoute, router, SESSION } from "../test/harness.js";
import { VerifyEmailPage } from "./VerifyEmailPage.js";

/**
 * The approved design shows "Verifying", "Verified" and "Link expired" as
 * three permanent reference states, stacked — not three states this page
 * switches between. So what a real check actually did has nowhere visible
 * of its own to render *to*; it can only move the reader on (a real success
 * redirects to `/welcome`, the same way a real password reset moves on to
 * `/login`) or leave them on the permanent "Link expired" card, which
 * already offers the one recovery action there is regardless of which of
 * unknown/expired/used applied (see `verify_email`'s own docstring for why
 * those three are indistinguishable on purpose).
 */

const AXE_OPTIONS = {
  rules: { "color-contrast": { enabled: false } },
} as const;

describe("the permanent reference states", () => {
  it("always shows all three, regardless of what a real check would find", () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail: vi.fn(() => new Promise<typeof SESSION>(() => undefined)),
    });

    renderRoute(<VerifyEmailPage />, { client, route: "/verify" });

    expect(screen.getByText(/checking your link/i)).toBeVisible();
    expect(screen.getByText(/email verified/i)).toBeVisible();
    expect(screen.getByText(/this link has expired/i)).toBeVisible();
    expect(screen.getByRole("link", { name: /continue/i })).toHaveAttribute("href", "/welcome");
    expect(screen.getByRole("button", { name: /send a new link/i })).toBeVisible();
  });

  it("passes an axe audit", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail: vi.fn(() => new Promise<typeof SESSION>(() => undefined)),
    });
    const { container } = renderRoute(<VerifyEmailPage />, { client, route: "/verify" });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("the real check running underneath", () => {
  it("moves the reader on to /welcome on a genuine success, rather than showing a second confirmation", async () => {
    const verifyEmail = vi.fn(() => Promise.resolve(SESSION));
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail,
    });

    renderRoute(<VerifyEmailPage />, { client, route: "/verify", search: "token=abc123" });

    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/welcome");
    });
    expect(verifyEmail).toHaveBeenCalledWith({ token: "abc123" });
  });

  it("checks the token exactly once, not once per render", async () => {
    const verifyEmail = vi.fn(() => Promise.resolve(SESSION));
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail,
    });

    renderRoute(<VerifyEmailPage />, { client, route: "/verify", search: "token=abc123" });
    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/welcome");
    });

    expect(verifyEmail).toHaveBeenCalledTimes(1);
  });

  it("does not ask the API about a missing token at all", () => {
    const verifyEmail = vi.fn();
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail,
    });

    renderRoute(<VerifyEmailPage />, { client, route: "/verify" });

    expect(verifyEmail).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("stays put on an unknown, expired, or already-used link — never redirects on a 409", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail: vi.fn(() => Promise.reject(apiError(409))),
    });

    renderRoute(<VerifyEmailPage />, { client, route: "/verify", search: "token=stale" });

    // No banner either: a 409 here is the expected, unremarkable case the
    // permanent "Link expired" card already exists to handle — not a
    // failure worth interrupting the reader about.
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("explains a real, unexpected failure without pretending the link worked", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail: vi.fn(() => Promise.reject(apiError(503))),
    });

    renderRoute(<VerifyEmailPage />, { client, route: "/verify", search: "token=abc123" });

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(router.replace).not.toHaveBeenCalled();
  });
});

describe("resending from the Link expired card", () => {
  function renderPage(
    overrides: Parameters<typeof createStubClient>[0] = {},
  ): ReturnType<typeof renderRoute> {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      verifyEmail: vi.fn(() => Promise.reject(apiError(409))),
      ...overrides,
    });
    return renderRoute(<VerifyEmailPage />, { client, route: "/verify", search: "token=stale" });
  }

  it("confirms once a fresh link is sent", async () => {
    const resendVerification = vi.fn(() => Promise.resolve({ status: "sent" }));
    renderPage({ resendVerification });

    await userEvent.click(screen.getByRole("button", { name: /send a new link/i }));

    expect(await screen.findByText(/fresh link is on its way/i)).toBeVisible();
    expect(resendVerification).toHaveBeenCalled();
  });

  it("explains that resending needs an active session, rather than a bare 401", async () => {
    renderPage({ resendVerification: vi.fn(() => Promise.reject(apiError(401))) });

    await userEvent.click(screen.getByRole("button", { name: /send a new link/i }));

    // Split across the embedded link, so matched in two pieces rather than
    // one regex spanning both text nodes. Exact name, since the page's own
    // permanent "Back to sign in" footer link would otherwise also match.
    expect(await screen.findByText(/and ask again from there/i)).toBeVisible();
    expect(screen.getByRole("link", { name: "sign in" })).toHaveAttribute("href", "/login");
  });

  it("says so when resending fails outright, and leaves the button usable", async () => {
    renderPage({ resendVerification: vi.fn(() => Promise.reject(apiError(503))) });

    await userEvent.click(screen.getByRole("button", { name: /send a new link/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeVisible();
    });
    expect(screen.getByRole("button", { name: /send a new link/i })).toBeEnabled();
  });
});
