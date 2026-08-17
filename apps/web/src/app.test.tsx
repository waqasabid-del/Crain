import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

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

const AXE_OPTIONS = {
  // Needs a canvas to sample pixels; jsdom has none. See `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

/** Every label in the primary navigation, so a destination added to the shell
 * without being reachable on a phone fails here rather than in the field. */
const DESTINATIONS = [
  "Daily brief",
  "Your record",
  "Activity",
  "Team",
  "Archive",
  "Workspace settings",
  "Preferences",
  "Trust Center",
] as const;

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
    expect(current[0]?.textContent).toMatch(/activity/i);
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

  it("hands focus to the main region when the skip link is used", async () => {
    // The previous test proves the link points somewhere real. This one proves
    // it does the thing it exists for: a skip link that scrolls without moving
    // focus leaves the next Tab back at the top of the navigation, which is
    // exactly the journey the reader was trying to avoid.
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });
    await screen.findByRole("navigation", { name: /primary/i });

    // First Tab from the document, because the skip link is only useful if it
    // is the first thing a keyboard user reaches.
    await userEvent.tab();
    const skip = screen.getByRole("link", { name: /skip to (main )?content/i });
    expect(skip).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("main")).toHaveFocus();
  });
});

/**
 * The narrow-viewport navigation.
 *
 * jsdom has no layout and no media queries, so none of this can assert that the
 * disclosure is the arrangement actually shown at 320px — that is the CSS's job
 * and a manual check's. What it can assert is the part that was broken and the
 * part that is easy to break again: that the control exists, that every
 * destination is behind it, and that a keyboard user can open it, use it, close
 * it with Escape and get their focus back. The strip this replaced put two
 * destinations, one of them the Trust page md/05 §B.6 requires to be permanently
 * reachable, off the right edge with no way to scroll to them by keyboard.
 */
describe("the narrow-viewport navigation", () => {
  async function openMenu(): Promise<HTMLElement> {
    const trigger = await screen.findByRole("button", { name: /menu/i });
    await userEvent.click(trigger);
    return trigger;
  }

  it("keeps every destination behind the disclosure", async () => {
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    const trigger = await openMenu();
    const panel = document.getElementById(trigger.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeNull();

    const nav = await screen.findByRole("navigation", { name: /primary/i });
    expect(panel?.contains(nav)).toBe(true);

    for (const label of DESTINATIONS) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("opens and closes from the keyboard alone", async () => {
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });
    const trigger = await screen.findByRole("button", { name: /menu/i });

    // Skip link, wordmark, then the disclosure: reachable in three keystrokes
    // from a cold start, before any of the destinations.
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await userEvent.keyboard("{Enter}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Focus lands inside the panel, so the next key press acts on the menu the
    // reader just opened rather than on the page behind it.
    const nav = screen.getByRole("navigation", { name: /primary/i });
    expect(within(nav).getByRole("link", { name: "Daily brief" })).toHaveFocus();

    // Tab continues through the destinations in order. The cycle is closed —
    // the panel covers the top of the page at this width — but it is closed
    // around the trigger, so the way out is one Shift+Tab away.
    await userEvent.tab();
    expect(within(nav).getByRole("link", { name: "Your record" })).toHaveFocus();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    // Without the return, focus falls to `<body>` when the panel is hidden and
    // the reader resumes tabbing from the top of the document with no
    // explanation for why.
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    const trigger = await openMenu();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await userEvent.keyboard("{Escape}");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("collapses again when a destination is chosen", async () => {
    renderRoute(shell(<BriefPage />), { client: signedIn(), route: "/" });

    const trigger = await openMenu();
    const nav = screen.getByRole("navigation", { name: /primary/i });
    await userEvent.click(within(nav).getByRole("link", { name: "Trust Center" }));

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("passes an axe audit with the menu open", async () => {
    // The closed shell is audited in `a11y.test.tsx`. Open is the state that
    // carries the new ARIA — `aria-expanded`, `aria-controls` and the id it
    // points at — and an audit that never opens the menu never sees any of it.
    const { container } = renderRoute(shell(<BriefPage />), {
      client: signedIn(),
      route: "/",
    });
    await openMenu();

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});
