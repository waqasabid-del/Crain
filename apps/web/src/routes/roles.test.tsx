import type { Consent, FactPage, Session } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { ROLE_PROFILES } from "../roles.js";
import { createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { MyWeekPage } from "./MyWeekPage.js";
import { SettingsPage } from "./SettingsPage.js";
import { WelcomePage } from "./WelcomePage.js";

/**
 * Step 26's exit criterion: **each of the five roles has a view that makes sense
 * without explanation.**
 *
 * The tests that matter are not "does the label render". They are the two
 * properties the feature has to preserve to be worth having at all:
 *
 * - **A role changes emphasis and never access.** The API asserts the data half
 *   (`test_roles.py`); this file asserts that no screen asks for something
 *   different because of what somebody said they do.
 * - **Saying nothing works.** md/11 §6 gives four roles a first screen and the
 *   product still has to be coherent for the person who skipped the question —
 *   which, on the screen where they have just been told their activity is
 *   readable, will be some of them.
 *
 * The designer case has a test of its own because md/08 §A.4 makes it an
 * adoption risk rather than a nicety: a designer whose first screen talks about
 * commits has already been told whose product this is.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

const CONSENT: Consent = {
  sources: [
    {
      source: "github",
      label: "GitHub",
      reads: "Commit messages, pull request titles and reviews.",
      optedOut: false,
    },
  ],
  refusals: ["CAIRN never scores or ranks people."],
};

const WEEK: FactPage = {
  items: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      kind: "decision",
      statement: "Priya set the direction for the onboarding flow in review.",
      certainty: "observed",
      origin: "extracted",
      validFrom: "2026-08-10T09:00:00Z",
      occurredAt: "2026-08-10T09:00:00Z",
      people: [{ mention: "Priya Nair" }],
      sources: [{ evidenceId: "msg-14", source: "chat" }],
    },
  ],
};

/** A session whose active workspace carries a stated work role. */
function sessionAs(workRole: string | null): Session {
  return {
    ...SESSION,
    workspaces: [{ ...SESSION.workspaces[0]!, workRole }],
  } as Session;
}

function client(workRole: string | null, overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(sessionAs(workRole))),
    myWeek: vi.fn(() => Promise.resolve(WEEK)),
    mySources: vi.fn(() => Promise.resolve(CONSENT)),
    setWorkRole: vi.fn(() => Promise.resolve({ workRole: null })),
    ...overrides,
  });
}

function renderWelcome(workRole: string | null, overrides = {}): void {
  renderRoute(
    <AppLayout>
      <WelcomePage />
    </AppLayout>,
    { client: client(workRole, overrides), route: "/welcome" },
  );
}

describe("saying what you do", () => {
  it("offers the five roles from the spec", async () => {
    // md/08 Part A names five, chosen for their relationship to the same data
    // rather than for job titles. A sixth in the interface would be a label with
    // no first screen behind it.
    renderWelcome(null);

    const question = await screen.findByRole("group", { name: /what do you do/i });
    for (const profile of ROLE_PROFILES) {
      expect(within(question).getByRole("radio", { name: profile.label })).toBeInTheDocument();
    }
  });

  it("offers not answering as plainly as answering", async () => {
    // A required question about what somebody does, on the screen where they
    // have just been told their activity is readable, reads as registration for
    // something.
    renderWelcome(null);

    const question = await screen.findByRole("group", { name: /what do you do/i });
    const decline = within(question).getByRole("radio", { name: /rather not say/i });

    expect(decline).toBeChecked();
    expect(screen.getByText(/everything else works exactly the same/i)).toBeVisible();
  });

  it("says what the answer does not do", async () => {
    // The question a sceptical reader is actually asking when a tool wants their
    // job title is whether it changes who can see what.
    renderWelcome(null);

    expect(
      await screen.findByText(/changes nothing about what you or anybody else can see/i),
    ).toBeVisible();
  });

  it("records the answer", async () => {
    const setWorkRole = vi.fn(() => Promise.resolve({ workRole: "designer" }));
    renderWelcome(null, { setWorkRole });

    const question = await screen.findByRole("group", { name: /what do you do/i });
    await userEvent.click(within(question).getByRole("radio", { name: /designer/i }));

    expect(setWorkRole).toHaveBeenCalledWith(SESSION.workspaces[0]?.workspace.id, "designer");
  });

  it("lets the answer be withdrawn with the same control", async () => {
    // The only way out of a wrong answer must not be a different wrong answer.
    const setWorkRole = vi.fn(() => Promise.resolve({ workRole: null }));
    renderWelcome("developer", { setWorkRole });

    const question = await screen.findByRole("group", { name: /what do you do/i });
    await userEvent.click(within(question).getByRole("radio", { name: /rather not say/i }));

    expect(setWorkRole).toHaveBeenCalledWith(SESSION.workspaces[0]?.workspace.id, null);
  });

  it("can be changed later without hunting for it", async () => {
    renderRoute(<SettingsPage />, { client: client("developer"), route: "/settings" });

    expect(await screen.findByRole("group", { name: /what do you do/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /engineer/i })).toBeChecked();
  });
});

describe("where CAIRN opens", () => {
  it.each([
    ["developer", /your record/i, "/me"],
    ["designer", /your record/i, "/me"],
    ["product", /team feed/i, "/feed"],
    ["operations", /team brief/i, "/"],
    ["founder", /team brief/i, "/"],
  ])("sends a %s onward to the right screen", async (role, label, href) => {
    // md/11 §6. The engineer and the designer land on their own record because
    // the first question a sceptical person has is what it says about them.
    renderWelcome(role);

    const onward = await screen.findByRole("link", { name: label });
    expect(onward).toHaveAttribute("href", href);
  });

  it("sends somebody who did not answer to the brief", async () => {
    // The screen that makes sense without knowing anything about the reader,
    // which is precisely the situation.
    renderWelcome(null);

    expect(await screen.findByRole("link", { name: /team brief/i })).toHaveAttribute("href", "/");
  });
});

describe("a role changes emphasis, never access", () => {
  it("asks for the same record whatever the reader said they do", async () => {
    // The property that keeps this a lens rather than a permission. The API
    // asserts the data half; this asserts that no screen requests something
    // different.
    const asDeveloper = client("developer");
    const asDesigner = client("designer");

    // Unmounted between renders: two copies of the same screen in one container
    // would make every query ambiguous for reasons that have nothing to do with
    // what is being asserted.
    const first = renderRoute(<MyWeekPage />, { client: asDeveloper, route: "/me" });
    await screen.findAllByText(/set the direction/i);
    first.unmount();

    renderRoute(<MyWeekPage />, { client: asDesigner, route: "/me" });
    await screen.findAllByText(/set the direction/i);

    const developerCall = (asDeveloper.myWeek as unknown as { mock: { calls: unknown[][] } }).mock
      .calls[0];
    const designerCall = (asDesigner.myWeek as unknown as { mock: { calls: unknown[][] } }).mock
      .calls[0];
    expect(developerCall).toEqual(designerCall);
  });

  it("shows the same facts to both", async () => {
    renderRoute(<MyWeekPage />, { client: client("operations"), route: "/me" });

    // Not a code-shaped fact, and it is on the screen for the role least likely
    // to be reading code.
    // Found more than once by design: the statement, and again inside the
    // citation disclosure's accessible name.
    expect(
      await screen.findAllByText(/set the direction for the onboarding flow/i),
    ).not.toHaveLength(0);
  });
});

describe("the designer's own record", () => {
  it("says that reviews and discussion count as much as code", async () => {
    // md/08 §A.4, mitigation 2 — shipped in place of a Figma connector, because
    // the risk is feeling unseen rather than lacking an integration.
    renderRoute(<MyWeekPage />, { client: client("designer"), route: "/me" });

    expect(
      await screen.findByText(/reviews, decisions and the conversations that set direction/i),
    ).toBeVisible();
  });

  it("does not open by talking about commits to anybody", async () => {
    // Including the person who said nothing: a default that assumed engineering
    // would be the invisible-work problem arriving one screen earlier.
    for (const role of [null, "designer", "operations"]) {
      const { unmount } = renderRoute(<MyWeekPage />, { client: client(role), route: "/me" });

      // The heading's own block: the title and the sentence under it, which is
      // the whole of what somebody reads before deciding how they feel about
      // this screen.
      const heading = await screen.findByRole("heading", { name: /my week/i });
      expect(heading.parentElement?.textContent ?? "").not.toMatch(/commits?\b/i);

      unmount();
    }
  });

  it("still counts code for the engineer", async () => {
    renderRoute(<MyWeekPage />, { client: client("developer"), route: "/me" });

    // No counts, no scores, no comparison — the commitment that holds for every
    // role, restated on the screen the sceptic opens first.
    expect(
      await screen.findByText(/nothing here is a count, a score, or a comparison/i),
    ).toBeVisible();
  });
});

describe("accessibility", () => {
  it("passes an axe audit with the question on screen", async () => {
    const { container } = renderRoute(<SettingsPage />, {
      client: client(null),
      route: "/settings",
    });
    await screen.findByRole("group", { name: /what do you do/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("names each option without reading its explanation as part of the name", async () => {
    // A label containing two sentences is announced in full every time focus
    // lands on the control, which is the sort of "accessible" markup that is
    // unusable in practice.
    renderRoute(<SettingsPage />, { client: client(null), route: "/settings" });

    const engineer = await screen.findByRole("radio", { name: "Engineer" });
    expect(engineer).toHaveAccessibleDescription(/no status reports/i);
  });
});
