import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { BriefPage } from "../routes/BriefPage.js";
import { LoginPage } from "../routes/LoginPage.js";
import { apiError, createStubClient, renderRoute, router, SESSION } from "../test/harness.js";

/** The protected tree: the guard, the shell, and a screen inside both. */
function protectedScreen(): ReactNode {
  return (
    <AppLayout>
      <BriefPage />
    </AppLayout>
  );
}

/**
 * Authentication, and the four states it can be in.
 *
 * The tests that matter here are the two that a "signed in or not" model gets
 * wrong: the first paint before the session check has answered, and a session
 * check that *failed* rather than returning nobody. Both send a signed-in reader
 * to a login form — one for a frame, one permanently — and both look like a bug
 * in the password rather than in the app.
 */

describe("the session check", () => {
  it("does not bounce a signed-in reader to login while it is still running", async () => {
    // The classic race: `getSession` has not resolved, so a two-state model
    // renders the signed-out branch and redirects. Whether the reader ever gets
    // back depends on which navigation wins.
    let resolveSession: (value: typeof SESSION) => void = () => undefined;
    const client = createStubClient({
      getSession: vi.fn(
        () =>
          new Promise<typeof SESSION>((resolve) => {
            resolveSession = resolve;
          }),
      ),
    });

    renderRoute(protectedScreen(), { client, route: "/" });

    expect(router.replace).not.toHaveBeenCalled();

    resolveSession(SESSION);
    await screen.findByRole("navigation", { name: /primary/i });
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("sends an anonymous visitor to the login screen", async () => {
    const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(null)) });

    renderRoute(protectedScreen(), { client, route: "/people" });

    // The redirect carries where the reader was going, so signing in lands
    // them there rather than on the brief.
    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/login?next=%2Fpeople");
    });
  });

  it("distinguishes 'the check failed' from 'you are signed out'", async () => {
    // A 500 is not an answer about who the reader is. Treating it as anonymous
    // offers a login form that cannot work either, and the failure presents as
    // "my password stopped working".
    const client = createStubClient({
      getSession: vi.fn(() => Promise.reject(apiError(500))),
    });

    renderRoute(protectedScreen(), { client, route: "/" });

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /try again/i })).toBeVisible();
  });

  it("recovers when the reader retries after a failed check", async () => {
    const getSession = vi
      .fn<() => Promise<typeof SESSION | null>>()
      .mockRejectedValueOnce(apiError(503))
      .mockResolvedValueOnce(SESSION);
    // The brief stays pending on purpose. Once the session recovers, the shell
    // mounts the protected screen, and an unstubbed getBrief rejects into a
    // SECOND alert that races the generic queryByRole("alert") below - green
    // or red depending on machine speed, which is how this passed locally and
    // failed in CI. This test is about the session check, not the brief.
    const client = createStubClient({
      getSession,
      getBrief: vi.fn(() => new Promise<never>(() => undefined)),
    });

    renderRoute(protectedScreen(), { client, route: "/" });
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(getSession).toHaveBeenCalledTimes(2);
  });
});

describe("signing in", () => {
  it("signs a reader in and shows them the app", async () => {
    // Anonymous on first check, signed in on every check after. The provider
    // re-reads the session once the credentials are accepted, so a stub pinned
    // to `null` would have the app sign the reader in and immediately conclude
    // they are not signed in.
    const getSession = vi
      .fn<() => Promise<typeof SESSION | null>>()
      .mockResolvedValueOnce(null)
      .mockResolvedValue(SESSION);
    const logIn = vi.fn(() => Promise.resolve(SESSION));
    const client = createStubClient({ getSession, logIn });

    renderRoute(<LoginPage />, { client, route: "/login", search: "next=%2Ffeed" });

    await userEvent.type(await screen.findByLabelText(/email/i), "ali@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/feed");
    });
    expect(logIn).toHaveBeenCalledWith({
      email: "ali@example.com",
      password: "correct-horse-battery",
    });
  });

  it("explains a rejected sign-in without blaming the reader", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      logIn: vi.fn(() => Promise.reject(apiError(401))),
    });

    renderRoute(<LoginPage />, { client, route: "/login" });

    await userEvent.type(await screen.findByLabelText(/email/i), "ali@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toBeVisible();
    // Copy that scolds is copy people remember. The message says what happened,
    // not what the reader did wrong.
    expect(alert.textContent.toLowerCase()).not.toMatch(/invalid|incorrect|failed to/);
  });

  it("does not leave the button disabled after a failure", async () => {
    // The bug that makes a recoverable error unrecoverable: `setSubmitting(true)`
    // without a `finally`, so one wrong password locks the form for good.
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      logIn: vi.fn(() => Promise.reject(apiError(401))),
    });

    renderRoute(<LoginPage />, { client, route: "/login" });

    await userEvent.type(await screen.findByLabelText(/email/i), "ali@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();
  });

  describe("SSO buttons and password reset", () => {
    // md/15 §3 specifies Google/GitHub SSO, and the approved design shows both
    // buttons — but no OAuth route exists anywhere in the API. A click must
    // say so honestly rather than doing nothing, navigating to a guessed URL,
    // or faking a session.
    //
    // "Forgot password?" is different: that feature now exists for real
    // (/forgot-password, backed by POST /v1/auth/forgot-password), so it is
    // a genuine link rather than a control that talks the reader out of
    // clicking it.

    it.each([
      ["Google", /continue with google/i],
      ["GitHub", /continue with github/i],
    ] as const)("offers %s per the approved design", (_provider, name) => {
      const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(null)) });
      renderRoute(<LoginPage />, { client, route: "/login" });

      expect(screen.getByRole("button", { name })).toBeVisible();
    });

    it.each([
      ["Google", /continue with google/i],
      ["GitHub", /continue with github/i],
    ] as const)(
      "says %s sign-in isn't available yet, rather than doing nothing or faking it",
      async (provider, name) => {
        const logIn = vi.fn();
        const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(null)), logIn });
        renderRoute(<LoginPage />, { client, route: "/login" });

        await userEvent.click(screen.getByRole("button", { name }));

        expect(await screen.findByRole("alert")).toHaveTextContent(
          new RegExp(`${provider} isn't available yet`, "i"),
        );
        expect(logIn).not.toHaveBeenCalled();
        expect(router.replace).not.toHaveBeenCalled();
      },
    );

    it("sends the reader to the real forgot-password page", () => {
      const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(null)) });
      renderRoute(<LoginPage />, { client, route: "/login" });

      expect(screen.getByRole("link", { name: /forgot password/i })).toHaveAttribute(
        "href",
        "/forgot-password",
      );
    });
  });
});

describe("signing out", () => {
  it("returns the reader to the login screen", async () => {
    const logOut = vi.fn(() => Promise.resolve());
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(SESSION)),
      logOut,
    });

    renderRoute(protectedScreen(), { client, route: "/settings" });

    // Scoped to the header, because the shell and the settings page each offer
    // a sign-out and an unscoped query is ambiguous. Ambiguity is worse than a
    // wrong selector: it passes until someone adds a second control, then fails
    // somewhere unrelated to the change that broke it.
    // `findByRole`, not `getByRole`: the session check is asynchronous, so a
    // synchronous query runs while the app is still showing its loading state
    // and reports the landmark as missing rather than as not-yet-rendered.
    const header = await screen.findByRole("banner");
    await userEvent.click(within(header).getByRole("button", { name: "Sign out" }));

    expect(logOut).toHaveBeenCalled();
    // Signing out drops to `anonymous`, and the guard redirects from there.
    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith(expect.stringContaining("/login"));
    });
  });
});
