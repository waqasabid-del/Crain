import type { InvitationPreview } from "@cairn/api-client";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { apiError, createStubClient, renderRoute, router } from "../test/harness.js";
import { InvitePage } from "./InvitePage.js";

/**
 * Redeeming an invitation now starts with a read-only preview
 * (`GET /v1/invitations/preview`), added alongside this page specifically so
 * the aside can say who is inviting whom, to where, before anyone accepts
 * anything. What follows tests that preview driving the real content, the
 * accept flow underneath it, and the edges a naive implementation gets
 * wrong: a missing token, and an invitation that no longer checks out.
 */

const AXE_OPTIONS = {
  rules: { "color-contrast": { enabled: false } },
} as const;

function preview(overrides: Partial<InvitationPreview> = {}): InvitationPreview {
  return {
    email: "priya@acme.test",
    role: "member",
    workspaceName: "Acme Labs",
    invitedByName: "M. Waqas",
    ...overrides,
  };
}

describe("opening an invitation", () => {
  it("says the link is incomplete when there is no token, rather than asking the API about nothing", () => {
    const previewInvitation = vi.fn();
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      previewInvitation,
    });

    renderRoute(<InvitePage />, { client, route: "/invite" });

    expect(screen.getByText(/link is incomplete/i)).toBeVisible();
    expect(previewInvitation).not.toHaveBeenCalled();
  });

  it("shows who is inviting whom, to where, before the reader does anything", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      previewInvitation: vi.fn(() => Promise.resolve(preview())),
    });

    renderRoute(<InvitePage />, { client, route: "/invite", search: "token=abc123" });

    expect(await screen.findByText(/you.ve been invited to acme labs/i)).toBeVisible();
    expect(screen.getByText(/m\. waqas invited you as a member/i)).toBeVisible();
    expect(screen.getByLabelText(/your email/i)).toHaveValue("priya@acme.test");
    expect(screen.getByLabelText(/your email/i)).toHaveAttribute("readonly");
  });

  it("explains an invitation that no longer checks out, rather than showing a workspace it isn't for", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      previewInvitation: vi.fn(() => Promise.reject(apiError(409, "invitation-invalid"))),
    });

    renderRoute(<InvitePage />, { client, route: "/invite", search: "token=stale" });

    expect(await screen.findByText(/invitation can.t be used/i)).toBeVisible();
    expect(screen.queryByLabelText(/your email/i)).not.toBeInTheDocument();
  });

  it("passes an axe audit once the invitation has loaded", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      previewInvitation: vi.fn(() => Promise.resolve(preview())),
    });
    const { container } = renderRoute(<InvitePage />, {
      client,
      route: "/invite",
      search: "token=abc123",
    });

    await screen.findByText(/you.ve been invited to acme labs/i);
    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("accepting", () => {
  function renderLoaded(
    overrides: Parameters<typeof createStubClient>[0] = {},
  ): ReturnType<typeof renderRoute> {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      previewInvitation: vi.fn(() => Promise.resolve(preview())),
      ...overrides,
    });
    return renderRoute(<InvitePage />, { client, route: "/invite", search: "token=abc123" });
  }

  it("accepts with the previewed email, and signs in afterwards rather than being signed in automatically", async () => {
    const acceptInvitation = vi.fn(() =>
      Promise.resolve({ id: "w1", name: "Acme Labs", slug: "acme-labs" }),
    );
    renderLoaded({ acceptInvitation });

    await screen.findByLabelText(/your email/i);
    await userEvent.type(screen.getByLabelText(/your name/i), "Priya Patel");
    await userEvent.type(screen.getByLabelText(/choose a password/i), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: /accept invitation/i }));

    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/login?next=%2Fwelcome");
    });
    expect(acceptInvitation).toHaveBeenCalledWith({
      token: "abc123",
      email: "priya@acme.test",
      password: "correct-horse-battery",
      displayName: "Priya Patel",
    });
  });

  it("omits the password entirely for someone who already has an account, rather than sending it empty", async () => {
    const acceptInvitation = vi.fn(() =>
      Promise.resolve({ id: "w1", name: "Acme Labs", slug: "acme-labs" }),
    );
    renderLoaded({ acceptInvitation });

    await screen.findByLabelText(/your email/i);
    await userEvent.click(screen.getByRole("button", { name: /accept invitation/i }));

    await waitFor(() => {
      expect(acceptInvitation).toHaveBeenCalledWith({ token: "abc123", email: "priya@acme.test" });
    });
  });

  it("explains a rejected acceptance without losing what was typed", async () => {
    renderLoaded({ acceptInvitation: vi.fn(() => Promise.reject(apiError(409))) });

    await screen.findByLabelText(/your email/i);
    await userEvent.type(screen.getByLabelText(/your name/i), "Priya Patel");
    await userEvent.click(screen.getByRole("button", { name: /accept invitation/i }));

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByLabelText(/your name/i)).toHaveValue("Priya Patel");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("lets the reader reveal the password they typed", async () => {
    renderLoaded();

    const passwordField = await screen.findByLabelText(/choose a password/i);
    await userEvent.type(passwordField, "correct-horse-battery");
    expect(passwordField).toHaveAttribute("type", "password");

    await userEvent.click(screen.getByRole("button", { name: /show password/i }));
    expect(passwordField).toHaveAttribute("type", "text");
  });

  it.each([
    ["Google", /accept with google/i],
    ["GitHub", /accept with github/i],
  ] as const)(
    "says %s isn't available yet, rather than doing nothing or faking it",
    async (provider, name) => {
      const acceptInvitation = vi.fn();
      renderLoaded({ acceptInvitation });

      await screen.findByLabelText(/your email/i);
      await userEvent.click(screen.getByRole("button", { name }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        new RegExp(`${provider} isn't available yet`, "i"),
      );
      expect(acceptInvitation).not.toHaveBeenCalled();
    },
  );
});
