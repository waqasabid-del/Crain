import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "./app/(app)/layout.js";
import { BriefPage } from "./routes/BriefPage.js";
import { FeedPage } from "./routes/FeedPage.js";
import { LoginPage } from "./routes/LoginPage.js";
import { PeoplePage } from "./routes/PeoplePage.js";
import { SettingsPage } from "./routes/SettingsPage.js";
import { createStubClient, renderRoute, SESSION } from "./test/harness.js";

/**
 * The automated half of Step 19's accessibility criterion.
 *
 * **What this can and cannot prove.** axe catches the mechanical failures that
 * are also the most common: an unlabelled control, a contrast ratio below the
 * threshold, a landmark nesting error, an `aria-*` value that is not valid for
 * its role. It cannot judge whether the reading order makes sense, whether an
 * error message is useful, or whether a screen-reader user could complete a
 * task. Those live in `app.test.tsx` as behavioural assertions and, eventually,
 * in a manual pass.
 *
 * Saying so matters because a green axe run is routinely mistaken for "this is
 * accessible". It means "none of the machine-checkable rules is broken", which
 * is a floor.
 *
 * **Colour contrast is explicitly disabled here, and that is not a dodge.**
 * axe's contrast rule needs a real canvas to sample rendered pixels; jsdom has
 * none, so the rule cannot run — it logs "getContext not implemented" and
 * reports nothing. Leaving it enabled would mean a green run that quietly
 * skipped the check, which is worse than a check that is honestly absent.
 * Contrast is covered where it can actually be measured: `packages/ui` asserts
 * every token pair against WCAG AA in both themes, with 39 tests.
 *
 * Document-level rules (`<html lang>`, landmark uniqueness across the page) are
 * also outside what a fragment render can see. `lang` is set in
 * `app/layout.tsx`; verifying it needs a browser-based audit, which belongs
 * with the deployment rather than here.
 */

/**
 * axe configuration shared by every audit.
 *
 * One place, so a rule cannot be disabled in one test and left enabled in
 * another — which is how a suite ends up with an exception nobody remembers
 * agreeing to.
 */
const AXE_OPTIONS = {
  rules: {
    // See above: cannot run in jsdom, and a rule that silently no-ops is worse
    // than one that is stated as absent.
    "color-contrast": { enabled: false },
  },
} as const;

const TWO_WORKSPACES: typeof SESSION = {
  ...SESSION,
  workspaces: [
    ...SESSION.workspaces,
    {
      role: "member",
      workspace: {
        id: "44444444-4444-4444-4444-444444444444",
        name: "Southwind",
        slug: "southwind",
      },
    },
  ],
};

function signedIn(session: typeof SESSION = SESSION): ReturnType<typeof createStubClient> {
  return createStubClient({ getSession: vi.fn(() => Promise.resolve(session)) });
}

async function auditShell(page: ReactNode, route: string): Promise<void> {
  const { container } = renderRoute(<AppLayout>{page}</AppLayout>, {
    client: signedIn(),
    route,
  });
  // Wait for the guard to resolve — auditing the loading state would pass
  // trivially and prove nothing about the screen.
  await screen.findByRole("navigation", { name: /primary/i });

  await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
}

describe("axe audit", () => {
  it("passes on the brief", async () => {
    await auditShell(<BriefPage />, "/");
  });

  it("passes on the feed", async () => {
    await auditShell(<FeedPage />, "/feed");
  });

  it("passes on people", async () => {
    await auditShell(<PeoplePage />, "/people");
  });

  it("passes on settings", async () => {
    await auditShell(<SettingsPage />, "/settings");
  });

  it("passes on the login screen", async () => {
    const { container } = renderRoute(<LoginPage />, {
      client: signedIn(),
      route: "/login",
    });
    await screen.findByRole("heading", { name: /sign in/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes with the workspace switcher present", async () => {
    // The switcher only renders with two or more memberships, so the
    // single-workspace audits above never reach it — and an unlabelled select
    // is exactly the failure axe exists to catch.
    const { container } = renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(TWO_WORKSPACES), route: "/" },
    );
    await screen.findByRole("combobox", { name: /workspace/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("the workspace switcher", () => {
  it("is absent when there is nothing to switch between", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(), route: "/" },
    );
    await screen.findByRole("navigation", { name: /primary/i });

    // A control offering one option cannot do anything, and every reader who
    // clicks it learns the interface wastes their attention. The workspace name
    // is still shown.
    expect(screen.queryByRole("combobox", { name: /workspace/i })).not.toBeInTheDocument();
    expect(screen.getByText("Northwind")).toBeVisible();
  });

  it("lists every membership and switches between them", async () => {
    // md/15 §3: contractors and agency staff routinely belong to several
    // workspaces. Before this existed the app showed `workspaces[0]` and gave
    // no indication the others were there.
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(TWO_WORKSPACES), route: "/" },
    );

    const switcher = await screen.findByRole("combobox", { name: /workspace/i });
    expect(switcher).toHaveValue(SESSION.workspaces[0]?.workspace.id);

    await userEvent.selectOptions(switcher, "44444444-4444-4444-4444-444444444444");
    expect(switcher).toHaveValue("44444444-4444-4444-4444-444444444444");
  });

  it("remembers the choice for the next session", async () => {
    const { unmount } = renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(TWO_WORKSPACES), route: "/" },
    );

    const switcher = await screen.findByRole("combobox", { name: /workspace/i });
    await userEvent.selectOptions(switcher, "44444444-4444-4444-4444-444444444444");
    unmount();

    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(TWO_WORKSPACES), route: "/" },
    );
    const reopened = await screen.findByRole("combobox", { name: /workspace/i });
    expect(reopened).toHaveValue("44444444-4444-4444-4444-444444444444");
  });

  it("ignores a remembered workspace the reader no longer belongs to", async () => {
    // A stored id outlives the membership that justified it — a contract ends,
    // someone is removed. Restoring it blindly would point every request at a
    // workspace the API refuses, which surfaces as a permission error on a
    // screen nobody chose to open.
    localStorage.setItem("cairn.workspace", "99999999-9999-9999-9999-999999999999");

    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(TWO_WORKSPACES), route: "/" },
    );

    const switcher = await screen.findByRole("combobox", { name: /workspace/i });
    expect(switcher).toHaveValue(SESSION.workspaces[0]?.workspace.id);
  });
});
