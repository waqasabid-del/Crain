import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { ForgotPasswordPage } from "./ForgotPasswordPage.js";

/**
 * Whose account this resets.
 *
 * Signed out — the ordinary case, since forgetting a password usually means
 * being unable to sign in — this is free text: there is no session to draw
 * an address from. Signed in, the address is locked to the caller's own
 * session email instead, the same reasoning `/invite`'s locked email field
 * already uses: a public form should not let a signed-in reader request a
 * reset for an address that is not theirs.
 */

describe("signed out", () => {
  it("accepts any address, since there is no session to restrict it to", async () => {
    const forgotPassword = vi.fn(() => Promise.resolve({ status: "sent" }));
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      forgotPassword,
    });

    renderRoute(<ForgotPasswordPage />, { client, route: "/forgot-password" });

    const field = await screen.findByLabelText(/^email$/i);
    expect(field).not.toHaveAttribute("readonly");

    await userEvent.type(field, "someone-else@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(forgotPassword).toHaveBeenCalledWith({ email: "someone-else@example.com" });
    });
  });
});

describe("signed in", () => {
  it("locks the field to the caller's own address, rather than a free-text one", async () => {
    const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(SESSION)) });

    renderRoute(<ForgotPasswordPage />, { client, route: "/forgot-password" });

    // Re-queried on each attempt, not captured once: the page renders the
    // free-text branch first (status starts "loading"), then swaps to the
    // locked branch as a distinct element once the session resolves.
    await waitFor(() => {
      expect(screen.getByLabelText(/^email$/i)).toHaveValue(SESSION.user.email);
    });
    expect(screen.getByLabelText(/^email$/i)).toHaveAttribute("readonly");
  });

  it("submits the session's own address, never anything typed elsewhere on the page", async () => {
    const forgotPassword = vi.fn(() => Promise.resolve({ status: "sent" }));
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(SESSION)),
      forgotPassword,
    });

    renderRoute(<ForgotPasswordPage />, { client, route: "/forgot-password" });

    await screen.findByLabelText(/^email$/i);
    await userEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(forgotPassword).toHaveBeenCalledWith({ email: SESSION.user.email });
    });
  });
});
