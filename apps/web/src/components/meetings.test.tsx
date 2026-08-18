import type {
  MeetingCaptureList,
  MeetingCaptureRequest,
  MyMeetingRequest,
  MyMeetingRequestList,
  Privacy,
  Session,
  Trust,
} from "@cairn/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { AdminPage } from "../routes/AdminPage.js";
import { SettingsPage } from "../routes/SettingsPage.js";
import { TrustPage } from "../routes/TrustPage.js";
import { apiError, createStubClient, MEMBERS, renderRoute, SESSION } from "../test/harness.js";

/**
 * Meeting consent, and the four things this feature must never do.
 *
 * **It must never record a meeting, or read as though it might.** CAIRN never
 * joins a meeting and no provider connector exists, so every state has to say so
 * in the words a person reads first — an administrator who believes they have
 * started a recording will tell their team they have.
 *
 * **It must never reveal who declined or who is silent.** The assertions below
 * check `innerHTML` as well as `textContent`, because the second catches the
 * failure the first cannot see: a count in a `title`, an `aria-label` or a
 * `data-` attribute is still on the page, and that is the form the leak is most
 * likely to take, since it looks like an accessibility improvement in review.
 * The subtler leak is arithmetic — "4 of 5 agreed" beside a refusal names the
 * refuser without printing anybody's name — so the tests assert against the
 * *shape* of a count, not only against names.
 *
 * **It must never lean on the answer.** No countdown, no pre-selected control,
 * no bulk agreement, and declining exactly as easy as agreeing: same variant,
 * same size, one click, one tab stop apart. That is asserted by comparing the
 * two buttons' classes rather than by reading the design, because a later
 * "primary" on the agree button would be a change nobody would describe as a
 * dark pattern in review.
 *
 * **It must never grow a per-person meeting measure** (md/03 §5.4). The
 * vocabulary test is deliberately blunt: the words are absent from these
 * sections entirely, including from sentences denying them, because a denial is
 * one edit away from being a feature description.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

const WORKSPACE = SESSION.workspaces[0]?.workspace.id ?? "";

/**
 * The platform's own handle for the meeting.
 *
 * Shaped like a real Google Meet code, because it is the field most likely to be
 * rendered by accident — it is the only human-readable string on the payload
 * that looks like a name, and it is also a joining code.
 */
const MEETING_REF = "abc-defg-hij";

/** The server's shared explanations, quoted rather than paraphrased: the gate in
 * `meetings/eligibility.py` is their only author, and a test matching a
 * paraphrase would keep passing on the day the server changed what it says. */
const AWAITING =
  "CAIRN is still waiting for everyone invited to answer. Nothing will be collected until they have.";
const REFUSED =
  "Somebody invited did not agree, so CAIRN will not collect anything from this meeting.";
const ALLOWED =
  "Everyone invited has agreed, so CAIRN may collect this meeting's transcript from the platform when it exists.";
const CLOSED = "This request is closed, so nothing will be collected.";
const WINDOW_PASSED =
  "This meeting finished without everyone agreeing, so nothing will be collected.";

const SELF_NOTICE =
  "Your answer, and nobody else's. You can change your mind at any time before " +
  "anything is collected, and each answer is added to the record rather than " +
  "replacing the last one. CAIRN never joins your meeting and never records " +
  "it; agreeing means only that it may later receive a transcript the meeting " +
  "platform itself produced. If anybody invited does not agree, nothing is " +
  "collected at all.";

const WORKSPACE_NOTICE =
  "Counts and states only. CAIRN cannot show you who agreed, who declined or " +
  "who has not answered — a screen that named them would make refusing cost " +
  "something, and a refusal that costs something is not a free choice. Nobody " +
  "in this workspace can answer on somebody else's behalf, including you: " +
  "every decision is written by the participant's own signed-in session.";

const PURPOSE = "Roadmap review, so the decisions do not have to be retold three times.";

function mine(overrides: Partial<MyMeetingRequest> = {}): MyMeetingRequest {
  return {
    id: "bbbbbbbb-0000-0000-0000-000000000001",
    provider: "google_meet",
    scheduledStart: "2026-09-12T13:00:00Z",
    scheduledEnd: "2026-09-12T14:00:00Z",
    purpose: PURPOSE,
    state: "pending",
    policyVersion: "2026-01-01",
    participantCount: 7,
    myDecision: null,
    myDecidedAt: null,
    canDecide: true,
    message: AWAITING,
    ...overrides,
  };
}

function myList(...requests: MyMeetingRequest[]): MyMeetingRequestList {
  return { requests, notice: SELF_NOTICE };
}

function capture(overrides: Partial<MeetingCaptureRequest> = {}): MeetingCaptureRequest {
  return {
    id: "cccccccc-0000-0000-0000-000000000001",
    provider: "zoom",
    scheduledStart: "2026-09-12T13:00:00Z",
    scheduledEnd: "2026-09-12T14:00:00Z",
    purpose: PURPOSE,
    state: "pending",
    policyVersion: "2026-01-01",
    requestedAt: "2026-09-01T09:00:00Z",
    participantCount: 7,
    acceptedCount: 3,
    eligible: false,
    reason: "awaiting_consent",
    message: AWAITING,
    ...overrides,
  };
}

function captureList(...requests: MeetingCaptureRequest[]): MeetingCaptureList {
  return {
    requests,
    totals: { pending: 1, eligible: 0, refused: 0, expired: 0, cancelled: 0, completed: 0 },
    notice: WORKSPACE_NOTICE,
  };
}

/** Enough of the privacy payload for the workspace screen to render around. */
const PRIVACY: Privacy = {
  retentionDays: 30,
  minRetentionDays: 7,
  maxRetentionDays: 365,
  region: "europe-west1",
};

const MEMBER: Session = {
  ...SESSION,
  workspaces: [{ ...SESSION.workspaces[0]!, role: "member" as const }],
};

// --------------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------------

function settingsClient(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMyMeetingRequests: vi.fn(() => Promise.resolve(myList(mine()))),
    ...overrides,
  });
}

function renderSettings(stub = settingsClient()): ReturnType<typeof renderRoute> {
  return renderRoute(<SettingsPage />, { client: stub, route: "/settings" });
}

function adminClient(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMembers: vi.fn(() => Promise.resolve(MEMBERS)),
    listIntegrations: vi.fn(() => Promise.resolve([])),
    getPrivacy: vi.fn(() => Promise.resolve(PRIVACY)),
    getAttributionHealth: vi.fn(() =>
      Promise.resolve({
        resolvedByProvider: {},
        unresolvedByProvider: {},
        disputed: 0,
        revoked: 0,
        notice: "Counts only.",
      }),
    ),
    getNotifications: vi.fn(() =>
      Promise.resolve({ memberCount: 2, optedOutCount: 0, people: [], sources: [] }),
    ),
    listMeetingCaptureRequests: vi.fn(() => Promise.resolve(captureList(capture()))),
    ...overrides,
  });
}

function renderAdmin(stub = adminClient()): ReturnType<typeof renderRoute> {
  return renderRoute(<AdminPage />, { client: stub, route: "/admin" });
}

/**
 * A section, once it has finished loading.
 *
 * Scoped so an assertion cannot pass on wording from elsewhere on the screen —
 * which matters more here than usual, since Preferences already carries a
 * paragraph about what CAIRN never does — and awaited past the skeleton, because
 * the heading is painted before the read resolves.
 */
async function section(name: RegExp | string): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name });
  const found = heading.closest("section");
  if (found === null) throw new Error("That heading is not inside a section");

  await waitFor(() => {
    expect(within(found).queryByText(/^loading /i)).toBeNull();
  });
  return found;
}

const mySection = (): Promise<HTMLElement> => section("Meeting privacy requests");
const workspaceSection = (): Promise<HTMLElement> => section("Meeting capture requests");

/**
 * The only request row on the workspace screen.
 *
 * Reached through the list's own accessible name rather than by role alone: the
 * boundary is a list too, and a bare `listitem` query would happily assert
 * against the sentence "CAIRN never joins a meeting" and pass forever.
 */
async function captureRow(): Promise<HTMLElement> {
  const found = await workspaceSection();
  const list = within(found).getByRole("list", { name: "Meeting capture requests" });
  const rows = within(list).getAllByRole("listitem");
  if (rows[0] === undefined) throw new Error("No capture request rendered");
  return rows[0];
}

// --------------------------------------------------------------------------
// The participant's own requests
// --------------------------------------------------------------------------

describe("the participant's own meeting requests", () => {
  it("asks only for the caller's own requests, with no subject", async () => {
    const listMyMeetingRequests = vi.fn(() => Promise.resolve(myList(mine())));
    renderSettings(settingsClient({ listMyMeetingRequests }));
    await mySection();

    // A workspace and request options, and nothing that could name a person.
    expect(listMyMeetingRequests).toHaveBeenCalledWith(WORKSPACE, expect.anything());
  });

  it("states the boundary, the terms, and how to withdraw", async () => {
    const found = await (renderSettings(), mySection());
    const text = found.textContent;

    // The platform, not CAIRN, makes any recording.
    expect(text).toContain("CAIRN never joins a meeting");
    expect(text).toMatch(/made by the meeting platform/i);
    expect(text).toMatch(/no recording and no transcript of its own/i);
    // What CAIRN could receive, and what it could never produce.
    expect(text).toMatch(/may later receive the text of a transcript/i);
    expect(text).toMatch(/never produces any per-person figure/i);
    // Declining is free, and it stops collection.
    expect(text).toMatch(/declining costs you nothing/i);
    expect(text).toMatch(/nothing from that meeting is collected/i);
    // Withdrawal, before anything is collected.
    expect(text).toMatch(
      /take your agreement back here at any point before anything is collected/i,
    );
    // The purpose, attributed to whoever wrote it.
    expect(text).toContain(PURPOSE);
    expect(text).toMatch(/in the requester’s words/i);
    // The server's own promise about the screen, rendered rather than rewritten.
    expect(text).toContain(SELF_NOTICE);
  });

  it("renders the meeting's window and never its platform reference", async () => {
    const { container } = renderSettings();
    const found = await mySection();

    const times = within(found).getAllByText((_, node) => node?.tagName === "TIME");
    expect(times.map((node) => node.getAttribute("datetime"))).toEqual([
      "2026-09-12T13:00:00Z",
      "2026-09-12T14:00:00Z",
    ]);

    // A joining code is not safer in an attribute, only less visible.
    expect(container.textContent).not.toContain(MEETING_REF);
    expect(container.innerHTML).not.toContain(MEETING_REF);
  });

  it("records an agreement against the caller's own request", async () => {
    const decideMeetingRequest = vi.fn(() => Promise.resolve(mine({ myDecision: "accepted" })));
    renderSettings(settingsClient({ decideMeetingRequest }));
    const found = await mySection();

    await userEvent.click(within(found).getByRole("button", { name: /^agree/i }));

    expect(decideMeetingRequest).toHaveBeenCalledWith(
      WORKSPACE,
      "bbbbbbbb-0000-0000-0000-000000000001",
      "accepted",
    );
    expect(await within(found).findByRole("status")).toHaveTextContent(
      /your agreement is recorded/i,
    );
  });

  it("records a decline in one click, the same as an agreement", async () => {
    const decideMeetingRequest = vi.fn(() => Promise.resolve(mine({ myDecision: "declined" })));
    renderSettings(settingsClient({ decideMeetingRequest }));
    const found = await mySection();

    await userEvent.click(within(found).getByRole("button", { name: /^decline/i }));

    expect(decideMeetingRequest).toHaveBeenCalledWith(
      WORKSPACE,
      "bbbbbbbb-0000-0000-0000-000000000001",
      "declined",
    );
    expect(decideMeetingRequest).toHaveBeenCalledTimes(1);
  });

  it("takes an agreement back", async () => {
    const decideMeetingRequest = vi.fn(() => Promise.resolve(mine({ myDecision: "withdrawn" })));
    renderSettings(
      settingsClient({
        listMyMeetingRequests: vi.fn(() =>
          Promise.resolve(
            myList(mine({ myDecision: "accepted", myDecidedAt: "2026-09-02T09:00:00Z" })),
          ),
        ),
        decideMeetingRequest,
      }),
    );
    const found = await mySection();

    await userEvent.click(within(found).getByRole("button", { name: /take my agreement back/i }));

    expect(decideMeetingRequest).toHaveBeenCalledWith(
      WORKSPACE,
      "bbbbbbbb-0000-0000-0000-000000000001",
      "withdrawn",
    );
  });

  it("marks only the answer in flight as busy, and blocks a double answer", async () => {
    let release: () => void = () => undefined;
    const decideMeetingRequest = vi.fn(
      () =>
        new Promise<MyMeetingRequest>((resolve) => {
          release = () => {
            resolve(mine({ myDecision: "declined" }));
          };
        }),
    );
    renderSettings(settingsClient({ decideMeetingRequest }));
    const found = await mySection();

    const agree = within(found).getByRole("button", { name: /^agree/i });
    const decline = within(found).getByRole("button", { name: /^decline/i });
    await userEvent.click(decline);

    expect(decline).toHaveAttribute("aria-busy", "true");
    // The other answer is disabled rather than also announced busy: two
    // mutually exclusive things cannot both be happening.
    expect(agree).toBeDisabled();
    expect(agree).not.toHaveAttribute("aria-busy");

    release();
    await waitFor(() => {
      expect(decideMeetingRequest).toHaveBeenCalledTimes(1);
    });
  });

  it("says an answer could not be recorded, and keeps the controls", async () => {
    renderSettings(
      settingsClient({ decideMeetingRequest: vi.fn(() => Promise.reject(apiError(500))) }),
    );
    const found = await mySection();

    await userEvent.click(within(found).getByRole("button", { name: /^decline/i }));

    expect(await within(found).findByRole("alert")).toHaveTextContent(
      /could not record your answer/i,
    );
    expect(within(found).getByRole("button", { name: /^decline/i })).toBeEnabled();
  });
});

// --------------------------------------------------------------------------
// No dark patterns
// --------------------------------------------------------------------------

describe("declining is exactly as easy as agreeing", () => {
  it("gives both answers the same weight, and neither a head start", async () => {
    renderSettings();
    const found = await mySection();

    const agree = within(found).getByRole("button", { name: /^agree/i });
    const decline = within(found).getByRole("button", { name: /^decline/i });

    // Same variant and size, so neither is visually recommended. Compared
    // rather than eyeballed: a "primary" added to the agree button later is a
    // change nobody would call a dark pattern in review.
    expect(decline.className).toBe(agree.className);
    // Both live in the same row, so neither is below a fold or behind a
    // disclosure the other is not.
    expect(decline.parentElement).toBe(agree.parentElement);
    expect(agree).toBeEnabled();
    expect(decline).toBeEnabled();
  });

  it("reaches decline in one tab stop from agree, and answers on Enter", async () => {
    const decideMeetingRequest = vi.fn(() => Promise.resolve(mine({ myDecision: "declined" })));
    renderSettings(settingsClient({ decideMeetingRequest }));
    const found = await mySection();

    const agree = within(found).getByRole("button", { name: /^agree/i });
    const decline = within(found).getByRole("button", { name: /^decline/i });

    agree.focus();
    await userEvent.tab();
    expect(decline).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(decideMeetingRequest).toHaveBeenCalledWith(
      WORKSPACE,
      "bbbbbbbb-0000-0000-0000-000000000001",
      "declined",
    );
  });

  it("pre-selects nothing, counts nothing down, and offers no bulk agreement", async () => {
    renderSettings(
      settingsClient({
        listMyMeetingRequests: vi.fn(() =>
          Promise.resolve(myList(mine(), mine({ id: "bbbbbbbb-0000-0000-0000-000000000002" }))),
        ),
      }),
    );
    const found = await mySection();

    // Nothing is checked, because there is nothing to check: consent given by a
    // control that arrives already ticked is not consent.
    expect(within(found).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(found).queryAllByRole("radio")).toHaveLength(0);
    // No bulk answer across requests, in either direction.
    expect(within(found).queryByRole("button", { name: /all/i })).toBeNull();
    // No urgency: no deadline, no countdown, nothing "expiring soon".
    expect(found.textContent).not.toMatch(
      /countdown|expires in|time left|hurry|only .* left|act now|soon/i,
    );
    // Two requests, two independent pairs of answers.
    expect(within(found).getAllByRole("button", { name: /^agree/i })).toHaveLength(2);
    expect(within(found).getAllByRole("button", { name: /^decline/i })).toHaveLength(2);
  });
});

// --------------------------------------------------------------------------
// States
// --------------------------------------------------------------------------

describe("what each state says", () => {
  it.each([
    ["awaiting everybody", mine(), /you have not answered yet/i, AWAITING],
    [
      "agreed by the reader",
      mine({ myDecision: "accepted", myDecidedAt: "2026-09-02T09:00:00Z" }),
      /you agreed/i,
      AWAITING,
    ],
    [
      "declined by the reader",
      mine({
        myDecision: "declined",
        myDecidedAt: "2026-09-02T09:00:00Z",
        state: "refused",
        canDecide: false,
        message: REFUSED,
      }),
      /you declined/i,
      REFUSED,
    ],
    [
      "withdrawn by the reader",
      mine({
        myDecision: "withdrawn",
        myDecidedAt: "2026-09-03T09:00:00Z",
        state: "refused",
        canDecide: false,
        message: REFUSED,
      }),
      /you took your agreement back/i,
      REFUSED,
    ],
    [
      "eligible for later collection",
      mine({
        myDecision: "accepted",
        myDecidedAt: "2026-09-02T09:00:00Z",
        state: "eligible",
        message: ALLOWED,
      }),
      /you agreed/i,
      ALLOWED,
    ],
    [
      "cancelled",
      mine({ state: "cancelled", canDecide: false, message: CLOSED }),
      /you have not answered yet/i,
      CLOSED,
    ],
    [
      "expired",
      mine({
        myDecision: "expired",
        state: "expired",
        canDecide: false,
        message: WINDOW_PASSED,
      }),
      /your answer expired/i,
      WINDOW_PASSED,
    ],
  ])(
    "says where a %s request stands, in the server's words",
    async (_name, request, own, shared) => {
      renderSettings(
        settingsClient({ listMyMeetingRequests: vi.fn(() => Promise.resolve(myList(request))) }),
      );
      const found = await mySection();

      expect(found.textContent).toMatch(own);
      // The shared explanation is the server's, which is written to name nobody.
      expect(found.textContent).toContain(shared);
    },
  );

  it("offers no answer once a request is closed, and says the record stands", async () => {
    renderSettings(
      settingsClient({
        listMyMeetingRequests: vi.fn(() =>
          Promise.resolve(myList(mine({ state: "cancelled", canDecide: false, message: CLOSED }))),
        ),
      }),
    );
    const found = await mySection();

    expect(within(found).queryByRole("button", { name: /^agree/i })).toBeNull();
    expect(within(found).queryByRole("button", { name: /^decline/i })).toBeNull();
    expect(found.textContent).toMatch(/this request is closed/i);
  });
});

// --------------------------------------------------------------------------
// Nobody else's decision
// --------------------------------------------------------------------------

describe("no other participant's decision is derivable", () => {
  it("names nobody, and prints no count of answers, on the reader's own screen", async () => {
    const { container } = renderSettings();
    const found = await mySection();
    const html = found.innerHTML;

    for (const value of ["jo@example.com", "Jo", "Ali Rahman", "ali@example.com"]) {
      expect(html).not.toContain(value);
    }
    // No "n of m", in text or in any attribute.
    expect(html).not.toMatch(/\d+\s*(of|out of)\s*\d+/i);
    // No statement about anybody else's answer.
    expect(html).not.toMatch(/(\d+|one|two|three)\s+(people|person)\s+(have|has|still)/i);
    expect(container.innerHTML).not.toContain(MEETING_REF);
  });

  it("prints no count at all beside a refusal", async () => {
    renderAdmin(
      adminClient({
        listMeetingCaptureRequests: vi.fn(() =>
          Promise.resolve(
            captureList(
              capture({
                state: "refused",
                // Withheld by the server precisely so that the refuser cannot
                // be identified by subtraction.
                acceptedCount: null,
                eligible: false,
                reason: "refused",
                message: REFUSED,
              }),
            ),
          ),
        ),
      }),
    );
    const row = await captureRow();

    // Not the number invited, not a number of answers, not a remainder.
    expect(row.innerHTML).not.toMatch(/\d+\s+(people|person)/i);
    expect(row.innerHTML).not.toMatch(/\d+\s*(of|out of)\s*\d+/i);
    expect(row.textContent).toMatch(/does not show how many people answered/i);
    expect(row.textContent).toContain(REFUSED);
  });

  it("never prints a partial count of agreements, or the number still to answer", async () => {
    // Seven invited, three agreed: the row must carry neither three nor four.
    renderAdmin();
    const row = await captureRow();

    expect(row.innerHTML).not.toMatch(/\d+\s*(of|out of)\s*\d+/i);
    expect(row.innerHTML).not.toMatch(/(3|three|4|four)\s+(people|person|agreed|answered)/i);
    expect(row.innerHTML).not.toMatch(/still to answer|yet to answer|waiting on \d/i);
    // What it does say: how many were asked, and that how they answered is not
    // this screen's to show.
    expect(row.textContent).toMatch(/7 people were invited to answer/i);
    expect(row.textContent).toMatch(/does not show you who has answered/i);
  });

  it("carries the server's promise that the workspace view holds no names", async () => {
    renderAdmin();
    const found = await workspaceSection();

    expect(found.textContent).toContain(WORKSPACE_NOTICE);
    for (const value of ["jo@example.com", "Ali Rahman", "ali@example.com"]) {
      expect(found.innerHTML).not.toContain(value);
    }
  });
});

// --------------------------------------------------------------------------
// No per-person meeting analysis
// --------------------------------------------------------------------------

describe("no per-person meeting analysis", () => {
  /** md/03 §5.4. Absent from the sections entirely — including from denials,
   * since a denial is one edit away from a feature description. */
  const FORBIDDEN = /talk time|score|rank|sentiment|coaching|attendance|most|least/i;

  it("keeps the vocabulary off the reader's own screen", async () => {
    renderSettings(
      settingsClient({
        listMyMeetingRequests: vi.fn(() =>
          Promise.resolve(
            myList(
              mine(),
              mine({
                id: "bbbbbbbb-0000-0000-0000-000000000002",
                myDecision: "accepted",
                state: "eligible",
                message: ALLOWED,
              }),
            ),
          ),
        ),
      }),
    );
    const found = await mySection();

    expect(found.innerHTML).not.toMatch(FORBIDDEN);
  });

  it("keeps the vocabulary off the workspace screen, in every state", async () => {
    renderAdmin(
      adminClient({
        listMeetingCaptureRequests: vi.fn(() =>
          Promise.resolve(
            captureList(
              capture(),
              capture({
                id: "cccccccc-0000-0000-0000-000000000002",
                state: "eligible",
                acceptedCount: 7,
                eligible: true,
                reason: "allowed",
                message: ALLOWED,
              }),
              capture({
                id: "cccccccc-0000-0000-0000-000000000003",
                state: "refused",
                acceptedCount: null,
                reason: "refused",
                message: REFUSED,
              }),
            ),
          ),
        ),
      }),
    );
    const found = await workspaceSection();

    expect(found.innerHTML).not.toMatch(FORBIDDEN);
  });
});

// --------------------------------------------------------------------------
// The workspace's requests
// --------------------------------------------------------------------------

describe("the workspace's capture requests", () => {
  it("says it asks permission and starts no recording", async () => {
    const found = await (renderAdmin(), workspaceSection());
    const text = found.textContent;

    expect(text).toMatch(/creating a request starts no recording/i);
    expect(text).toContain("CAIRN never joins a meeting");
    expect(text).toMatch(/each person invited answers for themselves/i);
    expect(text).toMatch(/no meeting platform connector exists in cairn yet/i);
  });

  it("says everybody agreed without saying who, once a request is eligible", async () => {
    renderAdmin(
      adminClient({
        listMeetingCaptureRequests: vi.fn(() =>
          Promise.resolve(
            captureList(
              capture({
                state: "eligible",
                acceptedCount: 7,
                eligible: true,
                reason: "allowed",
                message: ALLOWED,
              }),
            ),
          ),
        ),
      }),
    );
    const found = await workspaceSection();

    expect(found.textContent).toMatch(/everybody invited agreed/i);
    // Agreed does not mean collected: there is no connector to collect with.
    expect(found.textContent).toMatch(/nothing has been collected/i);
  });

  it("calls a request off after stating what that does", async () => {
    const cancelMeetingCaptureRequest = vi.fn(() =>
      Promise.resolve(capture({ state: "cancelled" })),
    );
    renderAdmin(adminClient({ cancelMeetingCaptureRequest }));
    const found = await workspaceSection();

    await userEvent.click(within(found).getByRole("button", { name: /call off this request/i }));
    expect(within(found).getByRole("group", { name: /call off this request/i })).toHaveTextContent(
      /nothing was collected, and nothing is deleted/i,
    );

    await userEvent.click(within(found).getByRole("button", { name: /^call off the request$/i }));
    expect(cancelMeetingCaptureRequest).toHaveBeenCalledWith(
      WORKSPACE,
      "cccccccc-0000-0000-0000-000000000001",
    );
  });

  it("offers no way to answer for a participant", async () => {
    renderAdmin();
    const found = await workspaceSection();

    for (const name of [/agree/i, /decline/i, /accept/i, /approve/i, /remind/i, /chase/i]) {
      expect(within(found).queryByRole("button", { name })).toBeNull();
    }
  });

  it("says who sees this, and where the reader's own answers are, when refused", async () => {
    renderAdmin(
      adminClient({
        listMeetingCaptureRequests: vi.fn(() => Promise.reject(apiError(403))),
      }),
    );
    const found = await workspaceSection();
    const alert = within(found).getByRole("alert");

    expect(alert).toHaveTextContent(/an owner or an admin of this workspace sees these/i);
    // Refused identically forever, so no "Try again" to teach the reader that
    // the product's buttons do not mean anything.
    expect(within(alert).queryByRole("button", { name: /try again/i })).toBeNull();
    expect(
      within(alert).getByRole("link", { name: /your own meeting privacy requests/i }),
    ).toHaveAttribute("href", "/settings");
  });
});

// --------------------------------------------------------------------------
// Who sees what
// --------------------------------------------------------------------------

describe("who sees what", () => {
  it("gives a member their own requests", async () => {
    renderSettings(settingsClient({ getSession: vi.fn(() => Promise.resolve(MEMBER)) }));

    expect(await screen.findByRole("heading", { name: "Meeting privacy requests" })).toBeVisible();
    expect(await screen.findByRole("button", { name: /^decline/i })).toBeEnabled();
  });

  it("does not give a member the workspace's requests", async () => {
    const listMeetingCaptureRequests = vi.fn(() => Promise.resolve(captureList(capture())));
    renderAdmin(
      adminClient({
        getSession: vi.fn(() => Promise.resolve(MEMBER)),
        listMeetingCaptureRequests,
      }),
    );

    await screen.findByRole("list", { name: /members/i });
    expect(
      screen.queryByRole("heading", { name: "Meeting capture requests" }),
    ).not.toBeInTheDocument();
    // Courtesy rather than protection — the API refuses independently — but the
    // request is not made either.
    expect(listMeetingCaptureRequests).not.toHaveBeenCalled();
  });

  it("gives an Owner both, since their own answer is theirs like anybody's", async () => {
    renderSettings();
    expect(await screen.findByRole("heading", { name: "Meeting privacy requests" })).toBeVisible();

    renderAdmin();
    expect(await screen.findByRole("heading", { name: "Meeting capture requests" })).toBeVisible();
  });
});

// --------------------------------------------------------------------------
// Loading, empty, error
// --------------------------------------------------------------------------

describe("the states every asynchronous surface has", () => {
  it("announces the load rather than showing a bare skeleton", async () => {
    renderSettings(
      settingsClient({ listMyMeetingRequests: vi.fn(() => new Promise<never>(() => undefined)) }),
    );

    // Awaited because the section itself waits on the session; a skeleton is
    // nothing at all to a screen reader, so this sentence is the announcement.
    const loading = await screen.findByText(/loading your meeting privacy requests/i);
    expect(loading.closest("[role='status']")).not.toBeNull();
  });

  it("says nobody has asked, rather than apologising for an empty list", async () => {
    renderSettings(
      settingsClient({ listMyMeetingRequests: vi.fn(() => Promise.resolve(myList())) }),
    );

    const heading = await screen.findByRole("heading", {
      name: /nobody has asked you about a meeting/i,
    });
    expect(heading).toBeVisible();
    expect(heading.closest("div")?.textContent ?? "").toMatch(
      /nothing from any meeting you attend is being collected/i,
    );
  });

  it("says nothing has been asked about, on the workspace screen", async () => {
    renderAdmin(
      adminClient({ listMeetingCaptureRequests: vi.fn(() => Promise.resolve(captureList())) }),
    );

    expect(
      await screen.findByRole("heading", { name: /no meeting has been asked about/i }),
    ).toBeVisible();
  });

  it("offers a retry and somewhere safe to go when the read fails", async () => {
    const listMyMeetingRequests = vi
      .fn<() => Promise<MyMeetingRequestList>>()
      .mockRejectedValueOnce(apiError(500))
      .mockResolvedValue(myList(mine()));
    renderSettings(settingsClient({ listMyMeetingRequests }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not be loaded/i);
    expect(
      within(alert).getByRole("link", { name: /what cairn does with meetings/i }),
    ).toHaveAttribute("href", "/trust");

    await userEvent.click(within(alert).getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("button", { name: /^decline/i })).toBeEnabled();
  });
});

// --------------------------------------------------------------------------
// The Trust Center
// --------------------------------------------------------------------------

describe("the Trust Center's meeting boundary", () => {
  const TRUST: Trust = {
    retentionDays: 30,
    region: "europe-west1",
    awaitingNotification: 0,
    sources: [],
    refusals: [],
    commitments: [],
    subprocessors: [],
  };

  function renderTrust(): ReturnType<typeof renderRoute> {
    return renderRoute(<TrustPage />, {
      client: createStubClient({
        getSession: vi.fn(() => Promise.resolve(SESSION)),
        getTrust: vi.fn(() => Promise.resolve(TRUST)),
        listIntegrations: vi.fn(() => Promise.resolve([])),
      }),
      route: "/trust",
    });
  }

  it("states the four parts of the boundary", async () => {
    renderTrust();
    const found = await section("Meetings");
    const text = found.textContent;

    expect(text).toMatch(/never joins a meeting/i);
    expect(text).toMatch(/does not appear as a participant or a bot/i);
    expect(text).toMatch(/only thing CAIRN could ever receive is an artifact the platform itself/i);
    expect(text).toMatch(/everybody invited has to agree first/i);
    expect(text).toMatch(/take their agreement back at any time before anything is collected/i);
    expect(text).toMatch(/no meeting platform connector exists in cairn yet/i);
  });

  it("does not claim that agreement is what makes CAIRN lawful", async () => {
    renderTrust();
    const found = await section("Meetings");
    const text = found.textContent;

    // md/03 §3.3: consent is not a valid basis in an employment context. The
    // page has to say what the basis actually is, and what agreement actually
    // does, without swapping one for the other.
    expect(text).toMatch(/safeguard CAIRN applies on top of its lawful basis/i);
    expect(text).toMatch(/legitimate interest, with a documented assessment/i);
    expect(text).not.toMatch(/consent is (the|our|its) (legal|lawful) basis/i);
    expect(text).not.toMatch(/lawful because you (agreed|consented)/i);
  });

  it("points the reader at their own answers", async () => {
    renderTrust();
    const found = await section("Meetings");

    expect(
      within(found).getByRole("link", { name: /meetings you have been asked about/i }),
    ).toHaveAttribute("href", "/settings");
  });
});

// --------------------------------------------------------------------------
// Accessibility
// --------------------------------------------------------------------------

describe("accessibility", () => {
  it("has no axe violations with both answers and a saved note on screen", async () => {
    const { container } = renderSettings(
      settingsClient({
        listMyMeetingRequests: vi.fn(() =>
          Promise.resolve(
            myList(
              mine(),
              mine({
                id: "bbbbbbbb-0000-0000-0000-000000000002",
                myDecision: "declined",
                myDecidedAt: "2026-09-02T09:00:00Z",
                state: "refused",
                canDecide: false,
                message: REFUSED,
              }),
            ),
          ),
        ),
        decideMeetingRequest: vi.fn(() => Promise.resolve(mine({ myDecision: "declined" }))),
      }),
    );
    const found = await mySection();

    await userEvent.click(within(found).getAllByRole("button", { name: /^decline/i })[0]!);
    await within(found).findByRole("status");

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("has no axe violations on the workspace screen, including while confirming", async () => {
    const { container } = renderAdmin();
    const found = await workspaceSection();

    await userEvent.click(within(found).getByRole("button", { name: /call off this request/i }));

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("has no axe violations in the empty and error states", async () => {
    const empty = renderSettings(
      settingsClient({ listMyMeetingRequests: vi.fn(() => Promise.resolve(myList())) }),
    );
    await screen.findByRole("heading", { name: /nobody has asked you about a meeting/i });
    await expect(axe(empty.container, AXE_OPTIONS)).resolves.toHaveNoViolations();
    empty.unmount();

    const failed = renderSettings(
      settingsClient({ listMyMeetingRequests: vi.fn(() => Promise.reject(apiError(500))) }),
    );
    await screen.findByRole("alert");
    await expect(axe(failed.container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("keeps every answer at or above the minimum target size", async () => {
    renderSettings();
    const found = await mySection();

    // The size is a token on the shared Button; asserting the size class is
    // present is what a jsdom test can honestly check, since jsdom computes no
    // layout. The token itself is 44px and is verified in @cairn/ui.
    const agree = within(found).getByRole("button", { name: /^agree/i });
    const decline = within(found).getByRole("button", { name: /^decline/i });
    expect(agree.className).toBe(decline.className);
    expect(agree.className).toMatch(/md/);
  });
});
