import { screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "./app/(app)/layout.js";
import { BriefPage } from "./routes/BriefPage.js";
import { FeedPage } from "./routes/FeedPage.js";
import NotFound from "./app/not-found.js";
import { PeoplePage } from "./routes/PeoplePage.js";
import { SettingsPage } from "./routes/SettingsPage.js";
import { createStubClient, renderRoute, SESSION } from "./test/harness.js";

function shell(page: ReactNode): ReactNode {
  return <AppLayout>{page}</AppLayout>;
}

/**
 * Routing, the shell, and the accessibility properties that are not optional.
 *
 * The a11y assertions here are deliberately behavioural rather than a rule
 * checker. A linter can prove an `aria-label` exists; only a test can prove the
 * skip link goes somewhere, that landmarks exist for a screen-reader user to
 * navigate by, and that the current page is announced rather than merely
 * coloured differently — which is the failure mode of a monochrome design
 * system in particular, because colour is not available to carry the signal.
 */

function signedIn(): ReturnType<typeof createStubClient> {
  return createStubClient({ getSession: vi.fn(() => Promise.resolve(SESSION)) });
}

describe("routing", () => {
  it("shows the brief at the root", async () => {
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    expect(await screen.findByRole("main")).toBeVisible();
    expect(await screen.findByRole("heading", { level: 1 })).toBeVisible();
  });

  it.each([
    ["/feed", <FeedPage key="feed" />],
    ["/people", <PeoplePage key="people" />],
    ["/settings", <SettingsPage key="settings" />],
  ])("renders %s inside the shell", async (route, page) => {
    renderRoute(shell(page), { client: signedIn(), route });

    const main = await screen.findByRole("main");
    expect(within(main).getByRole("heading", { level: 1 })).toBeVisible();
  });

  it("offers a way back from an address that does not exist", async () => {
    // A 404 that is a dead end makes a mistyped URL feel like a broken product.
    // Rendered without the shell: the page is public, so a signed-out visitor
    // following a stale link learns it is broken rather than being asked to
    // sign in first and finding out afterwards.
    renderRoute(<NotFound />, { client: signedIn(), route: "/nothing-here" });

    expect(await screen.findByRole("link", { name: /brief|home/i })).toBeVisible();
  });
});

describe("the shell", () => {
  it("exposes the landmarks a screen-reader user navigates by", async () => {
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    expect(await screen.findByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("marks the current page for assistive technology, not only visually", async () => {
    // In a monochrome design system this is not a nicety. There is no colour
    // available to carry "you are here", so if it is not in the accessibility
    // tree it is not conveyed at all to a reader who cannot see the weight
    // difference.
    renderRoute(shell(<FeedPage />), { client: signedIn(), route: "/feed" });

    const nav = await screen.findByRole("navigation", { name: /primary/i });
    const current = within(nav)
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page");

    expect(current).toHaveLength(1);
    expect(current[0]?.textContent).toMatch(/feed/i);
  });

  it("has a skip link that points at the main region", async () => {
    // Keyboard users should not tab through the whole navigation on every page.
    // The link is only useful if its target exists and is focusable — a skip
    // link to a missing anchor is worse than none, because it looks provided.
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    const skip = await screen.findByRole("link", { name: /skip to (main )?content/i });
    const target = skip.getAttribute("href")?.replace("#", "");

    expect(target).toBeTruthy();
    const main = await screen.findByRole("main");
    expect(main.id).toBe(target);
    // `tabIndex={-1}` so that following the link actually moves focus. Without
    // it the browser scrolls and leaves focus where it was, and the next Tab
    // returns to the navigation.
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("names every navigation destination in text", async () => {
    // An icon-only nav is unusable to a screen reader and ambiguous to everyone
    // else. Accessible names come from content here, not from a title attribute.
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    const nav = await screen.findByRole("navigation", { name: /primary/i });
    const links = within(nav).getAllByRole("link");

    expect(links.length).toBeGreaterThanOrEqual(4);
    for (const link of links) {
      expect(link.textContent.trim()).not.toBe("");
    }
  });
});
