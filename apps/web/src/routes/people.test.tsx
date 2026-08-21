import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, MEMBERS, renderRoute, SESSION } from "../test/harness.js";
import { PeoplePage } from "./PeoplePage.js";

/**
 * The team list, and the one line it is allowed to say about identity.
 *
 * A members list is where comparative measurement between people first appears
 * in almost every product of this kind: an activity column, a "last seen", a
 * count of anything. md/05 §B.3.3 makes that a change of product rather than a
 * change of style, so the tests here are almost entirely about absence.
 *
 * Attribution transparency pulls at exactly this boundary, because the obvious
 * place to show "who has not connected an account" is next to the list of
 * people. That would be a connection leaderboard with a polite name. What this
 * screen says instead is addressed to the reader about their own record, and
 * these tests hold it there.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMembers: vi.fn(() => Promise.resolve(MEMBERS)),
    // A benign default rather than the harness's `unexpected`: the pending
    // invitations card reads on every render of this screen for an Owner or
    // Admin, and letting it reject would put a second `role="alert"` on every
    // test above that is about something else entirely. No outstanding
    // invitations is also the honest default for a fresh workspace.
    listInvitations: vi.fn(() => Promise.resolve([])),
    ...overrides,
  });
}

function renderPeople(stub = client()): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <PeoplePage />
    </AppLayout>,
    { client: stub, route: "/people" },
  );
}

describe("the team list", () => {
  it("lists who is here and what each of them can configure", async () => {
    renderPeople();

    // A card each now, with the name as the heading that opens their page.
    const heading = await screen.findByRole("heading", { name: /ali rahman/i });
    expect(heading).toBeVisible();
    // Owner is shown because it says who can configure the workspace. What a
    // card leads with is the person's job roles; "Member" and "Viewer" are
    // permission plumbing and deliberately never printed on a person.
    const list = screen.getByRole("list", { name: /people in this workspace/i });
    expect(within(list).getByText("Owner")).toBeVisible();
    expect(within(list).queryByText(/^(?:member|viewer)$/i)).toBeNull();
  });

  it("carries no ranking, score or per-person count of anything", async () => {
    // The assertion the whole screen exists to keep passing. It is written as a
    // vocabulary check rather than a structural one because the failure arrives
    // as a friendly-looking column, not as a refactor.
    renderPeople();
    await screen.findByRole("heading", { name: /ali rahman/i });

    const main = await screen.findByRole("main");
    const text = main.textContent;

    expect(text).not.toMatch(/\b(?:most|top|least|rank\w*|score\w*|leaderboard)\b/i);
    expect(text).not.toMatch(/\bcommits?\b/i);
    expect(text).not.toMatch(/\bcontributions?\b/i);
    expect(text).not.toMatch(/\b(?:activity|facts|items)\s+count\b/i);
    expect(text).not.toMatch(/\blast\s+(?:seen|active)\b/i);
  });

  it("says nothing about any colleague's connected accounts", async () => {
    // The tempting feature, and the one that turns this page into a list of
    // people to chase. Whether somebody has connected an account is theirs.
    renderPeople();
    await screen.findByRole("heading", { name: /ali rahman/i });

    const list = screen.getByRole("list", { name: /people in this workspace/i });
    expect(list.textContent).not.toMatch(/connected|unresolved|identit/i);
  });

  it("says so when the team cannot be loaded, with a way to try again", async () => {
    renderPeople(client({ listMembers: vi.fn(() => Promise.reject(new Error("offline"))) }));

    expect(await screen.findByRole("heading", { name: /could not be loaded/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /try again/i })).toBeVisible();
  });

  it("explains an empty workspace rather than showing an empty grid", async () => {
    renderPeople(client({ listMembers: vi.fn(() => Promise.resolve([])) }));

    expect(await screen.findByRole("heading", { name: /nobody here yet/i })).toBeVisible();
  });

  it("passes an axe audit with the notes on screen", async () => {
    const { container } = renderPeople();
    await screen.findByRole("heading", { name: /ali rahman/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("self-declared capacity on the list", () => {
  it("wears the person's own words, labelled self-reported", async () => {
    renderPeople();

    // MEMBERS in the harness: one open_to_work, one not_stated.
    expect(await screen.findByText("Open to new work — self-reported")).toBeVisible();
    // The chip itself carries whose words these are - the page no longer
    // repeats it in a standing note, so the label on the chip is the promise.
  });

  it("renders no chip for a person who stated nothing", async () => {
    renderPeople();

    // Absence of a declaration is not information: a dash, not a state.
    expect(await screen.findAllByLabelText("No availability stated")).not.toHaveLength(0);
  });
});

describe("inviting a colleague", () => {
  it("offers the invite panel to an owner and sends to the address given", async () => {
    const invite = vi.fn(() =>
      Promise.resolve({ id: "inv-1", email: "new@example.com", role: "member" }),
    );
    renderPeople(client({ invite }));

    await screen.findByRole("heading", { name: /ali rahman/i });
    await userEvent.click(screen.getByRole("button", { name: /invite member/i }));

    await userEvent.type(screen.getByLabelText(/email address/i), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send invitation/i }));

    expect(invite).toHaveBeenCalledWith(SESSION.workspaces[0]!.workspace.id, {
      email: "new@example.com",
      role: "member",
    });
    // The confirmation names the address and nothing else: the token that
    // redeems the invitation reaches the invitee's inbox and nowhere else.
    expect(await screen.findByText(/invitation sent to new@example.com/i)).toBeVisible();
    const main = await screen.findByRole("main");
    expect(main.textContent).not.toMatch(/token|paste this link/i);
  });

  it("reports a refused invitation without clearing what was typed", async () => {
    renderPeople(client({ invite: vi.fn(() => Promise.reject(apiError(409))) }));

    await screen.findByRole("heading", { name: /ali rahman/i });
    await userEvent.click(screen.getByRole("button", { name: /invite member/i }));
    await userEvent.type(screen.getByLabelText(/email address/i), "taken@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send invitation/i }));

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByLabelText(/email address/i)).toHaveValue("taken@example.com");
  });

  it("does not offer the panel to a member", async () => {
    const viewerSession = {
      ...SESSION,
      workspaces: [{ ...SESSION.workspaces[0]!, role: "member" as const }],
    };
    renderPeople(client({ getSession: vi.fn(() => Promise.resolve(viewerSession)) }));

    await screen.findByRole("heading", { name: /ali rahman/i });
    expect(screen.queryByRole("button", { name: /invite member/i })).toBeNull();
  });
});

/**
 * Noon on a day `days` from today, as an ISO timestamp.
 *
 * Noon rather than "now plus N × 24h" on purpose: the expiry wording counts
 * calendar days, so a test built from the current clock time would slide onto
 * the neighbouring date whenever it ran near midnight, and across a daylight
 * saving boundary as well.
 */
function inDays(days: number): string {
  const at = new Date();
  at.setHours(12, 0, 0, 0);
  at.setDate(at.getDate() + days);
  return at.toISOString();
}

const WORKSPACE_ID = SESSION.workspaces[0]!.workspace.id;

const INVITATIONS = [
  { id: "inv-9", email: "kim@example.com", role: "member" as const, expiresAt: inDays(3) },
  { id: "inv-8", email: "sam@example.com", role: "admin" as const, expiresAt: inDays(-2) },
];

/**
 * The invitations that have been sent and not yet accepted.
 *
 * Sending one used to be the whole feature, which meant an admin could issue an
 * invitation and then had no way to see it existed, tell it apart from somebody
 * who had actually joined, or take it back. These tests are about the half that
 * was missing — and about the boundary the rest of this file guards, since a
 * queue of outstanding letters is not a list of people to chase.
 */
describe("invitations that are still outstanding", () => {
  it("lists each address, what it would grant, and exactly when it runs out", async () => {
    renderPeople(client({ listInvitations: vi.fn(() => Promise.resolve(INVITATIONS)) }));

    const pending = await screen.findByRole("list", { name: /pending invitations/i });
    expect(within(pending).getByText("kim@example.com")).toBeVisible();
    expect(within(pending).getByText("sam@example.com")).toBeVisible();
    // Exact, never "soon": an admin deciding whether to invite somebody again
    // needs to know whether the link in that person's inbox still works.
    expect(within(pending).getByText("Expires in 3 days")).toBeVisible();
    expect(within(pending).getByText("Expired")).toBeVisible();
    // The role in plain words, not the wire value it was sent as.
    expect(
      within(pending).getByText(/can read everything and correct their own record/i),
    ).toBeVisible();
  });

  it("says so plainly when nobody is waiting", async () => {
    renderPeople();

    expect(await screen.findByRole("heading", { name: /no pending invitations/i })).toBeVisible();
  });

  it("asks before withdrawing, then withdraws that one and re-reads the list", async () => {
    const listInvitations = vi.fn(() => Promise.resolve(INVITATIONS));
    const withdrawInvitation = vi.fn(() => Promise.resolve());
    renderPeople(client({ listInvitations, withdrawInvitation }));

    await screen.findByRole("list", { name: /pending invitations/i });

    // The first click arms; it must not send anything. The control names the
    // address, so the reader hears which invitation they are about to end.
    await userEvent.click(
      screen.getByRole("button", { name: "Withdraw the invitation to kim@example.com" }),
    );
    expect(withdrawInvitation).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", {
        name: "Confirm withdrawing the invitation to kim@example.com",
      }),
    );

    expect(withdrawInvitation).toHaveBeenCalledWith(WORKSPACE_ID, "inv-9");
    // Re-read rather than crossed off locally: a refused withdrawal that had
    // already erased the row would leave a live link looking withdrawn.
    await waitFor(() => {
      expect(listInvitations).toHaveBeenCalledTimes(2);
    });
  });

  it("shows an invitation just sent without a reload", async () => {
    const fresh = {
      id: "inv-2",
      email: "new@example.com",
      role: "member" as const,
      expiresAt: inDays(7),
    };
    let reads = 0;
    const listInvitations = vi.fn(() => {
      reads += 1;
      return Promise.resolve(reads === 1 ? [] : [fresh]);
    });
    renderPeople(client({ listInvitations, invite: vi.fn(() => Promise.resolve(fresh)) }));

    await screen.findByRole("heading", { name: /no pending invitations/i });
    await userEvent.click(screen.getByRole("button", { name: /invite member/i }));
    await userEvent.type(screen.getByLabelText(/email address/i), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: /send invitation/i }));

    const pending = await screen.findByRole("list", { name: /pending invitations/i });
    expect(within(pending).getByText("new@example.com")).toBeVisible();
  });

  it("keeps the team on screen when the invitations cannot be read", async () => {
    // Two reads, two failures, two places to say so. One panel going down must
    // not take the other with it.
    renderPeople(client({ listInvitations: vi.fn(() => Promise.reject(apiError(500))) }));

    expect(
      await screen.findByRole("heading", { name: /pending invitations could not be loaded/i }),
    ).toBeVisible();
    expect(await screen.findByRole("heading", { name: /ali rahman/i })).toBeVisible();
  });

  it("shows a member neither the invite panel nor who has been invited", async () => {
    const memberSession = {
      ...SESSION,
      workspaces: [{ ...SESSION.workspaces[0]!, role: "member" as const }],
    };
    const listInvitations = vi.fn(() => Promise.resolve(INVITATIONS));
    renderPeople(
      client({ getSession: vi.fn(() => Promise.resolve(memberSession)), listInvitations }),
    );

    await screen.findByRole("heading", { name: /ali rahman/i });
    expect(screen.queryByRole("button", { name: /invite member/i })).toBeNull();
    expect(screen.queryByRole("list", { name: /pending invitations/i })).toBeNull();
    // Not merely hidden: who has been invited is never even asked for.
    expect(listInvitations).not.toHaveBeenCalled();
  });
});
