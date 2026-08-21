import type { Session } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell.js";
import { createStubClient, renderRoute, SESSION } from "../test/harness.js";

/**
 * The application frame: grouping, workspace identity, the current location and
 * the narrow-viewport disclosure.
 *
 * jsdom has no layout, so none of this proves what the sidebar looks like. What
 * it does prove is the part that is invisible and easy to break: that the group
 * labels are real headings rather than styled text, that the workspace name is
 * the one in the session rather than a placeholder, that exactly one link claims
 * `aria-current`, and that a keyboard user can open, use and close the menu.
 */

function sessionAs(role: "owner" | "admin" | "member" | "viewer"): Session {
  const [entry] = SESSION.workspaces;
  if (entry === undefined) throw new Error("the shared SESSION has no workspace");
  return { ...SESSION, workspaces: [{ ...entry, role }] };
}

function signedIn(session: Session = SESSION): ReturnType<typeof createStubClient> {
  return createStubClient({ getSession: vi.fn(() => Promise.resolve(session)) });
}

function renderShell(options: { session?: Session; route?: string } = {}): void {
  const { session = SESSION, route = "/" } = options;
  renderRoute(
    <AppShell>
      <h1>A page</h1>
    </AppShell>,
    { client: signedIn(session), route },
  );
}

async function primaryNav(): Promise<HTMLElement> {
  return screen.findByRole("navigation", { name: /primary/i });
}

describe("the grouped navigation", () => {
  it("labels each group with a real heading", async () => {
    // A group label that exists only as small grey text is decoration: a screen
    // reader user arrives at "Workspace settings" with no idea which section it
    // belongs to, because there is nothing in the accessibility tree to say so.
    renderShell();
    const nav = await primaryNav();

    for (const label of ["Workspace", "Administration", "Trust & privacy"]) {
      expect(within(nav).getByRole("heading", { name: label })).toBeVisible();
    }
  });

  it("puts every destination in its group, in order", async () => {
    renderShell();
    const nav = await primaryNav();

    const groups: Record<string, string[]> = {
      // The overview is the home screen and the brief has its own route: the
      // dashboard answers "what is happening", the brief is the document a
      // reader sits down with, and Projects is the surface the project layer
      // made truthful.
      Workspace: [
        "Dashboard",
        "Daily brief",
        "Projects",
        "Activity",
        "Team",
        "Your record",
        "Archive",
      ],
      Administration: ["Workspace settings", "Preferences"],
      "Trust & privacy": ["Trust Center"],
    };

    for (const [group, labels] of Object.entries(groups)) {
      // The list is named by its heading, so the association is asserted the way
      // assistive technology reads it rather than by DOM position.
      const list = within(nav).getByRole("list", { name: group });
      const links = within(list).getAllByRole("link");
      expect(links.map((link) => link.textContent)).toEqual(labels);
    }
  });

  it("keeps every route path that existed before the regrouping", async () => {
    renderShell();
    const nav = await primaryNav();
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));

    // Every path that existed before is still here; `/brief` and `/projects`
    // are additions, not replacements - the brief moved off `/` when the
    // overview took the home slot, and its old content is one click away.
    expect(hrefs).toEqual([
      "/",
      "/brief",
      "/projects",
      "/feed",
      "/people",
      "/me",
      "/archive",
      "/admin",
      "/settings",
      "/trust",
    ]);
  });

  it.each(["owner", "admin"] as const)("offers workspace settings to an %s", async (role) => {
    renderShell({ session: sessionAs(role) });
    const nav = await primaryNav();

    expect(within(nav).getByRole("link", { name: "Workspace settings" })).toBeVisible();
  });

  it.each(["member", "viewer"] as const)(
    "does not offer workspace settings to a %s",
    async (role) => {
      // A courtesy, never a control: the API enforces. Hiding it keeps a member
      // from walking into a page that can only refuse them.
      renderShell({ session: sessionAs(role) });
      const nav = await primaryNav();

      expect(within(nav).queryByRole("link", { name: "Workspace settings" })).toBeNull();
      // The group survives, because Preferences is not gated.
      expect(within(nav).getByRole("link", { name: "Preferences" })).toBeVisible();
    },
  );
});

describe("workspace identity", () => {
  it("shows the workspace name carried by the session", async () => {
    renderShell();

    expect(await screen.findByText("Northwind")).toBeVisible();
  });

  it("does not offer a switcher when the reader belongs to one workspace", async () => {
    // A dropdown with a single option is an affordance that cannot do anything.
    renderShell();
    await primaryNav();

    expect(screen.queryByRole("combobox", { name: /workspace/i })).toBeNull();
  });

  it("offers a switcher when the session carries several workspaces", async () => {
    const [entry] = SESSION.workspaces;
    if (entry === undefined) throw new Error("the shared SESSION has no workspace");
    renderShell({
      session: {
        ...SESSION,
        workspaces: [
          entry,
          {
            role: "member",
            workspace: {
              id: "44444444-4444-4444-4444-444444444444",
              name: "Contoso",
              slug: "contoso",
            },
          },
        ],
      },
    });

    const switcher = await screen.findByRole("combobox", { name: /workspace/i });
    expect(within(switcher).getByRole("option", { name: "Contoso" })).toBeInTheDocument();
  });

  it("states the role the session carries, and invents none", async () => {
    renderShell({ session: sessionAs("member") });

    expect(await screen.findByText("Member")).toBeVisible();
  });

  it("keeps sign-out in the shell", async () => {
    renderShell();

    expect(await screen.findByRole("button", { name: /sign out/i })).toBeVisible();
    expect(screen.getByText("Ali Rahman")).toBeVisible();
  });
});

describe("the current location", () => {
  it("marks exactly one link, and marks it in the accessibility tree", async () => {
    renderShell({ route: "/people" });
    const nav = await primaryNav();

    const current = within(nav)
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page");

    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Team");
  });

  it("does not mark the overview on every page", async () => {
    // "/" prefix-matches every path; without the exact match two links claim to
    // be where the reader is and the quieter one is still wrong.
    renderShell({ route: "/archive" });
    const nav = await primaryNav();

    expect(within(nav).getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(nav).getByRole("link", { name: "Archive" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("marks a child route as its section", async () => {
    renderShell({ route: "/archive/2026-03-19" });
    const nav = await primaryNav();

    expect(within(nav).getByRole("link", { name: "Archive" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("the narrow-viewport menu", () => {
  it("opens and closes from the keyboard, returning focus to the trigger", async () => {
    renderShell();
    const trigger = await screen.findByRole("button", { name: /menu/i });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // Focus enters the panel, so the next key press acts on the menu rather
    // than on the page behind it.
    const nav = await primaryNav();
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("keeps Tab inside the open menu", async () => {
    // The panel covers the top of the page on a phone. Tabbing past it lands the
    // reader in content they cannot see with the menu still open; the trigger
    // stays in the cycle so the way out is always one Shift+Tab away.
    renderShell();
    const trigger = await screen.findByRole("button", { name: /menu/i });
    await userEvent.click(trigger);

    const nav = await primaryNav();
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveFocus();

    await userEvent.tab({ shift: true });
    expect(trigger).toHaveFocus();

    await userEvent.tab({ shift: true });
    expect(screen.getByRole("button", { name: /sign out/i })).toHaveFocus();
  });

  it("collapses when a destination is chosen", async () => {
    renderShell();
    const trigger = await screen.findByRole("button", { name: /menu/i });
    await userEvent.click(trigger);

    const nav = await primaryNav();
    await userEvent.click(within(nav).getByRole("link", { name: "Trust Center" }));

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});

describe("the skip link", () => {
  it("is the first stop and moves focus to the main region", async () => {
    renderShell();
    await primaryNav();

    await userEvent.tab();
    const skip = screen.getByRole("link", { name: /skip to (main )?content/i });
    expect(skip).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    const main = screen.getByRole("main");
    expect(main).toHaveFocus();
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(main.id).toBe(skip.getAttribute("href")?.replace("#", ""));
  });
});
