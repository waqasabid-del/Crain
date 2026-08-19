import type { Consent, FactPage } from "@cairn/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, router, SESSION } from "../test/harness.js";
import { InvitePage } from "./InvitePage.js";
import { WelcomePage } from "./WelcomePage.js";

/**
 * Step 23's exit criterion: **a new team member's first screen is their own
 * record, and opt-out works per source.**
 *
 * md/11 §4.1 calls this the most consequential screen in the product, and the
 * reason is that the same information handled two ways produces two different
 * products. A compliance notice — "your employer has enabled activity
 * monitoring" — is read as surveillance, and the developer becomes the blocker.
 * An invitation carrying a promise is read as a tool.
 *
 * So several of these tests assert on *copy and ordering*, which is unusual and
 * correct here: the framing is the feature. The word "monitoring" appearing on
 * this page would be a defect in the same way a missing citation is a defect
 * elsewhere.
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
      reads: "Commit messages, pull request titles and reviews. Never the contents of your code.",
      optedOut: false,
    },
    {
      source: "meeting",
      label: "Meetings",
      reads: "Transcripts of meetings your workspace connects. Never audio, and never a recording.",
      optedOut: false,
    },
  ],
  refusals: [
    "CAIRN never scores or ranks people.",
    "CAIRN is never used to make employment decisions.",
  ],
};

const WEEK: FactPage = {
  items: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      kind: "delivery",
      statement: "Priya shipped rate limiting to production.",
      certainty: "observed",
      origin: "extracted",
      validFrom: "2026-08-10T09:00:00Z",
      occurredAt: "2026-08-10T09:00:00Z",
      people: [{ mention: "Priya Nair" }],
      sources: [{ evidenceId: "ev-pr-482", source: "github" }],
    },
  ],
};

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    myWeek: vi.fn(() => Promise.resolve(WEEK)),
    mySources: vi.fn(() => Promise.resolve(CONSENT)),
    ...overrides,
  });
}

function renderWelcome(stub = client()): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <WelcomePage />
    </AppLayout>,
    { client: stub, route: "/welcome" },
  );
}

describe("their own record, first", () => {
  it("leads with what CAIRN has about the reader", async () => {
    renderWelcome();

    // md/11 §4.1: "the first thing a team member sees is their own contribution
    // record... That single sequence communicates 'this is yours' more
    // effectively than any amount of policy copy."
    const record = await screen.findByRole("heading", { name: /your record/i });
    const reads = await screen.findByRole("heading", { name: /what cairn reads/i });
    const refusals = await screen.findByRole("heading", { name: /what cairn never does/i });

    // Asserted by document order, because the ordering *is* the argument.
    const position = record.compareDocumentPosition(reads);
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reads.compareDocumentPosition(refusals) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    expect((await screen.findAllByText(/shipped rate limiting/i)).length).toBeGreaterThan(0);
  });

  it("offers correcting as the first thing the reader can do to it", async () => {
    // The other half of §4.1's sequence: the first *action* available is
    // correcting the record, not acknowledging a notice. This screen shows a
    // preview of the record (the approved design's compact treatment) with a
    // link to the full correction flow at `/me`, rather than the inline
    // correction controls themselves — correcting is still one click away,
    // just not duplicated onto this screen too.
    renderWelcome();

    expect(
      await screen.findByRole("link", { name: /correct anything that.s wrong/i }),
    ).toHaveAttribute("href", "/me");
  });

  it("does not describe itself as monitoring or tracking", async () => {
    // Not a euphemism: the page states plainly what is read, which is more
    // specific than either word. But those two words are the ones that make a
    // person reach for the opt-out before finishing the sentence they are in.
    renderWelcome();
    await screen.findByRole("heading", { name: /what cairn never does/i });

    const main = await screen.findByRole("main");
    expect(main.textContent).not.toMatch(/monitor(?:ing|ed)?\b/i);
    expect(main.textContent).not.toMatch(/\btracking\b/i);
    expect(main.textContent).not.toMatch(/\bsurveillance\b/i);
  });

  it("states what CAIRN refuses to do, at the moment the reader is deciding", async () => {
    // md/05 §B.3.4 requires the refusals in-product. Here rather than on a
    // policy page, because this is when somebody is deciding whether to trust
    // it — and a promise they have to go looking for is one they never read.
    renderWelcome();

    expect(await screen.findByText(/never scores or ranks people/i)).toBeVisible();
    expect(screen.getByText(/never used to make employment decisions/i)).toBeVisible();
  });
});

describe("inline per-source opt-out", () => {
  it("offers every source with what it reads, in the notification itself", async () => {
    // md/11 §4.1: "offers per-source opt-out **in the notification itself**,
    // not buried in settings". A control somebody has to go looking for is one
    // they conclude was hidden on purpose.
    renderWelcome();

    await screen.findByRole("heading", { name: /what cairn reads/i });
    const toggles = screen.getAllByRole("checkbox", { name: /do not attribute/i });

    expect(toggles).toHaveLength(2);
    expect(screen.getByText(/never the contents of your code/i)).toBeVisible();
    expect(screen.getByText(/never audio, and never a recording/i)).toBeVisible();
  });

  it("records the choice for one source without touching the others", async () => {
    const setSourceConsent = vi.fn(() =>
      Promise.resolve({ source: "github", optedOut: true, unlinked: 3 }),
    );
    renderWelcome(client({ setSourceConsent }));

    await screen.findByRole("heading", { name: /what cairn reads/i });
    const [github] = screen.getAllByRole("checkbox", { name: /do not attribute/i });
    await userEvent.click(github!);

    expect(setSourceConsent).toHaveBeenCalledWith(SESSION.workspaces[0]?.workspace.id, {
      source: "github",
      optedOut: true,
    });
    expect(setSourceConsent).toHaveBeenCalledTimes(1);
  });

  it("says what the choice actually did", async () => {
    // A control that visibly did something is a control a person believes. A
    // silent toggle asks them to take it on faith at exactly the moment they
    // have decided not to.
    renderWelcome(
      client({
        setSourceConsent: vi.fn(() =>
          Promise.resolve({ source: "github", optedOut: true, unlinked: 3 }),
        ),
      }),
    );

    await screen.findByRole("heading", { name: /what cairn reads/i });
    const [github] = screen.getAllByRole("checkbox", { name: /do not attribute/i });
    await userEvent.click(github!);

    expect(await screen.findByRole("status")).toHaveTextContent(
      /3 things are no longer attributed to you/i,
    );
  });

  it("is honest that opting back in does not restore what was removed", async () => {
    renderWelcome(
      client({
        mySources: vi.fn(() =>
          Promise.resolve({
            ...CONSENT,
            sources: [{ ...CONSENT.sources![0]!, optedOut: true }],
          }),
        ),
        setSourceConsent: vi.fn(() =>
          Promise.resolve({ source: "github", optedOut: false, unlinked: 0 }),
        ),
      }),
    );

    await screen.findByRole("heading", { name: /what cairn reads/i });
    const [github] = screen.getAllByRole("checkbox", { name: /do not attribute/i });
    expect(github).toBeChecked();

    await userEvent.click(github!);
    expect(await screen.findByRole("status")).toHaveTextContent(/stays removed/i);
  });

  it("says so when a choice cannot be saved, and leaves the control usable", async () => {
    // A privacy control that fails silently is worse than one that is missing:
    // the person believes they opted out and did not.
    renderWelcome(client({ setSourceConsent: vi.fn(() => Promise.reject(apiError(503))) }));

    await screen.findByRole("heading", { name: /what cairn reads/i });
    const [github] = screen.getAllByRole("checkbox", { name: /do not attribute/i });
    await userEvent.click(github!);

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(github).toBeEnabled();
    expect(github).not.toBeChecked();
  });

  it("passes an axe audit", async () => {
    const { container } = renderWelcome();
    await screen.findByRole("heading", { name: /what cairn never does/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

const INVITATION_PREVIEW = {
  email: "priya@acme.test",
  role: "member",
  workspaceName: "Acme Labs",
  invitedByName: "M. Waqas",
};

describe("the invitation", () => {
  it("reads as an invitation rather than a notice", async () => {
    const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
    renderRoute(<InvitePage />, {
      client: client({ previewInvitation }),
      route: "/invite",
      search: "token=abc",
    });

    expect(await screen.findByRole("heading", { name: /invited to acme labs/i })).toBeVisible();
    // Who invited them, and to what — before what the form needs from them.
    expect(screen.getByText(/m\. waqas invited you as a member/i)).toBeVisible();
    expect(screen.getByText(/nothing is scored, ranked, or used against anyone/i)).toBeVisible();
  });

  it("sends a new member to their own record, not the team brief", async () => {
    // The exit criterion, at the routing level. Landing on the brief would make
    // the first thing a new member sees a page about everybody else.
    const acceptInvitation = vi.fn(() => Promise.resolve(SESSION.workspaces[0]!.workspace));
    const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
    renderRoute(<InvitePage />, {
      client: client({ acceptInvitation, previewInvitation }),
      route: "/invite",
      search: "token=abc",
    });

    await userEvent.type(
      await screen.findByLabelText(/choose a password/i),
      "correct-horse-battery",
    );
    await userEvent.click(screen.getByRole("button", { name: /accept invitation/i }));

    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/login?next=%2Fwelcome");
    });
  });

  it("explains a broken link rather than failing at submit", async () => {
    renderRoute(<InvitePage />, { client: client(), route: "/invite" });

    expect(await screen.findByRole("heading", { name: /link is incomplete/i })).toBeVisible();
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
  });

  it("explains an invitation that no longer checks out, rather than showing a form for it", async () => {
    const previewInvitation = vi.fn(() => Promise.reject(apiError(409)));
    renderRoute(<InvitePage />, {
      client: client({ previewInvitation }),
      route: "/invite",
      search: "token=stale",
    });

    expect(await screen.findByRole("heading", { name: /can.t be used/i })).toBeVisible();
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
  });

  it("shows the invited address locked, rather than asking the reader to retype it", async () => {
    const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
    renderRoute(<InvitePage />, {
      client: client({ previewInvitation }),
      route: "/invite",
      search: "token=abc",
    });

    const emailField = await screen.findByLabelText(/your email/i);
    expect(emailField).toHaveValue("priya@acme.test");
    expect(emailField).toHaveAttribute("readonly");
  });

  it("does not require a password from somebody who already has an account", async () => {
    const acceptInvitation = vi.fn(() => Promise.resolve(SESSION.workspaces[0]!.workspace));
    const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
    renderRoute(<InvitePage />, {
      client: client({ acceptInvitation, previewInvitation }),
      route: "/invite",
      search: "token=abc",
    });

    await screen.findByLabelText(/your email/i);
    await userEvent.click(screen.getByRole("button", { name: /accept invitation/i }));

    // Omitted, not sent empty: the API takes a password only when the person
    // has no account, and "" is not the same as "not applicable".
    await waitFor(() => {
      expect(acceptInvitation).toHaveBeenCalledWith({ token: "abc", email: "priya@acme.test" });
    });
  });

  describe("SSO buttons", () => {
    // The approved design shows both, but no OAuth route exists anywhere in
    // the API — same gap as the sign-in and signup pages. A click must say
    // so honestly rather than doing nothing or faking acceptance.

    it.each([
      ["Google", /accept with google/i],
      ["GitHub", /accept with github/i],
    ] as const)("offers %s per the approved design", async (_provider, name) => {
      const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
      renderRoute(<InvitePage />, {
        client: client({ previewInvitation }),
        route: "/invite",
        search: "token=abc",
      });

      expect(await screen.findByRole("button", { name })).toBeVisible();
    });

    it.each([
      ["Google", /accept with google/i],
      ["GitHub", /accept with github/i],
    ] as const)(
      "says %s acceptance isn't available yet, rather than doing nothing or faking it",
      async (provider, name) => {
        const acceptInvitation = vi.fn();
        const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
        renderRoute(<InvitePage />, {
          client: client({ acceptInvitation, previewInvitation }),
          route: "/invite",
          search: "token=abc",
        });

        await userEvent.click(await screen.findByRole("button", { name }));

        expect(await screen.findByRole("alert")).toHaveTextContent(
          new RegExp(`${provider} isn't available yet`, "i"),
        );
        expect(acceptInvitation).not.toHaveBeenCalled();
        expect(router.replace).not.toHaveBeenCalled();
      },
    );
  });

  it("passes an axe audit", async () => {
    const previewInvitation = vi.fn(() => Promise.resolve(INVITATION_PREVIEW));
    const { container } = renderRoute(<InvitePage />, {
      client: client({ previewInvitation }),
      route: "/invite",
      search: "token=abc",
    });
    await screen.findByRole("heading", { name: /invited to acme labs/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("the shell", () => {
  it("does not advertise the welcome screen in navigation", async () => {
    // It is a moment, not a destination. A permanent "Welcome" link would make
    // the notification look like a page somebody could be sent back to, and
    // would take a navigation slot from a screen people use daily.
    renderWelcome();

    const nav = await screen.findByRole("navigation", { name: /primary/i });
    expect(within(nav).queryByRole("link", { name: /welcome/i })).not.toBeInTheDocument();
  });
});
