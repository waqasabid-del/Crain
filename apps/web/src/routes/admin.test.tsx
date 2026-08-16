import type { Integration, Notifications, Privacy, SupportSession, Trust } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, MEMBERS, renderRoute, SESSION } from "../test/harness.js";
import { AdminPage } from "./AdminPage.js";
import { TrustPage } from "./TrustPage.js";

/**
 * Step 25's exit criterion: **an Owner can manage the workspace without
 * contacting support.**
 *
 * Most of what that needs is ordinary, and the ordinary parts are tested by
 * asserting that the choice reaches the request. Three things are not ordinary
 * and are why this file is long:
 *
 * - **The member list must never gain a column about how much somebody did.**
 *   This is the exact screen where "last active" first seems reasonable, because
 *   every other product's admin area has one. A test asserts its absence.
 * - **Opt-outs are a number, never a list of names.** A list beside "opted out"
 *   is a list of employees who declined to be recorded, handed to whoever writes
 *   their review.
 * - **The Trust & Privacy Center is open to everybody and states this
 *   workspace's own numbers.** A page about trust that some of the team cannot
 *   open, or that quotes a retention period nothing enforces, has done the
 *   opposite of its job.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

const WORKSPACE = SESSION.workspaces[0]?.workspace.id ?? "";

const INTEGRATIONS: Integration[] = [
  {
    source: "github",
    account: "acme-inc",
    installationId: 42,
    connectedAt: "2026-06-01T09:00:00Z",
    disconnectedAt: null,
    suspended: false,
  },
];

const PRIVACY: Privacy = {
  retentionDays: 365,
  minRetentionDays: 7,
  maxRetentionDays: 730,
  region: "us-central1",
};

const NOTIFICATIONS: Notifications = {
  people: [
    {
      userId: SESSION.user.id,
      email: "ali@example.com",
      displayName: "Ali Rahman",
      notifiedAt: "2026-08-01T09:00:00Z",
    },
    {
      userId: "33333333-3333-3333-3333-333333333333",
      email: "jo@example.com",
      displayName: null,
      notifiedAt: null,
    },
  ],
  memberCount: 2,
  optedOutCount: 1,
  sources: ["github", "chat", "meeting", "document"],
};

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMembers: vi.fn(() => Promise.resolve(MEMBERS)),
    listIntegrations: vi.fn(() => Promise.resolve(INTEGRATIONS)),
    getPrivacy: vi.fn(() => Promise.resolve(PRIVACY)),
    getNotifications: vi.fn(() => Promise.resolve(NOTIFICATIONS)),
    ...overrides,
  });
}

function renderAdmin(stub = client()): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <AdminPage />
    </AppLayout>,
    { client: stub, route: "/admin" },
  );
}

describe("members", () => {
  it("lists who is here and what they may configure", async () => {
    renderAdmin();

    const members = await screen.findByRole("list", { name: /members/i });
    expect(within(members).getByText("Ali Rahman")).toBeVisible();
    expect(within(members).getByText("jo@example.com")).toBeVisible();
  });

  it("says nothing about how much anybody did", async () => {
    // The commitment, asserted on the screen where it would first be broken.
    // Roles govern configuration, never how much is visible about a person
    // (md/15 §2.2) — and an activity column here is how that inverts.
    renderAdmin();

    const members = await screen.findByRole("list", { name: /members/i });
    expect(members.textContent).not.toMatch(/last (active|seen)|activity|commits?|contributions?/i);
  });

  it("sends a role change", async () => {
    const changeRole = vi.fn(() => Promise.resolve(MEMBERS[1]!));
    renderAdmin(client({ changeRole }));

    const select = await screen.findByLabelText(/role for jo@example.com/i);
    await userEvent.selectOptions(select, "Admin");

    expect(changeRole).toHaveBeenCalledWith(WORKSPACE, MEMBERS[1]?.userId, "admin");
  });

  it("offers the reader no controls over their own row", async () => {
    // The API refuses a self-role-change, and a control that always fails is
    // worse than no control: it teaches somebody the product is broken.
    renderAdmin();

    await screen.findByRole("list", { name: /members/i });
    expect(screen.queryByLabelText(/role for ali@example.com/i)).not.toBeInTheDocument();
  });

  it("says what removal does before doing it", async () => {
    // A confirmation that restates the consequence is one somebody can decline.
    // "Are you sure?" is a button people learn to click without reading.
    const removeMember = vi.fn(() => Promise.resolve());
    renderAdmin(client({ removeMember }));

    await screen.findByRole("list", { name: /members/i });
    await userEvent.click(screen.getAllByRole("button", { name: /^remove$/i })[0]!);

    expect(screen.getByText(/what cairn already recorded about their work stays/i)).toBeVisible();
    expect(removeMember).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /remove their access/i }));
    expect(removeMember).toHaveBeenCalledWith(WORKSPACE, MEMBERS[1]?.userId);
  });

  it("explains a refusal rather than failing silently", async () => {
    // The last-Owner rule lives in the API. What matters here is that its
    // refusal reaches the person who tried.
    renderAdmin(client({ changeRole: vi.fn(() => Promise.reject(apiError(422))) }));

    const select = await screen.findByLabelText(/role for jo@example.com/i);
    await userEvent.selectOptions(select, "Viewer");

    expect(await screen.findByRole("alert")).toBeVisible();
  });
});

describe("connected sources", () => {
  it("says what GitHub reads, and what it never reads", async () => {
    renderAdmin();

    expect(await screen.findByText(/never the contents of your code/i)).toBeVisible();
  });

  it("is honest that disconnecting does not remove what was captured", async () => {
    // Disconnecting is "stop reading", not "forget what you read". The second is
    // a deletion request about everybody's shared history, and not a side effect
    // of a button labelled Disconnect.
    renderAdmin();

    expect(
      await screen.findByText(/does not remove what has already been recorded/i),
    ).toBeVisible();
  });

  it("disconnects the installation the reader is looking at", async () => {
    const disconnectGitHub = vi.fn(() => Promise.resolve());
    renderAdmin(client({ disconnectGitHub }));

    await userEvent.click(await screen.findByRole("button", { name: /disconnect/i }));

    expect(disconnectGitHub).toHaveBeenCalledWith(WORKSPACE, 42);
  });

  it("explains a quiet feed when an integration is disconnected", async () => {
    // A gap in the feed is explained by "GitHub was disconnected on the 4th" and
    // unexplained by silence, which is why disconnected rows are listed at all.
    renderAdmin(
      client({
        listIntegrations: vi.fn(() =>
          Promise.resolve([{ ...INTEGRATIONS[0]!, disconnectedAt: "2026-08-04T09:00:00Z" }]),
        ),
      }),
    );

    expect(await screen.findByText(/no longer reading from this account/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: /disconnect/i })).not.toBeInTheDocument();
  });
});

describe("privacy and data", () => {
  it("says what retention covers and what it does not", async () => {
    // Raw payloads go; what CAIRN understood stays. Stated rather than left for
    // an administrator to discover from an empty archive.
    renderAdmin();

    expect(await screen.findByText(/the messages and payloads themselves/i)).toBeVisible();
    expect(
      screen.getByText(/are the team's record|team&rsquo;s record|team's record/i),
    ).toBeVisible();
  });

  it("sends a new retention period", async () => {
    const setRetention = vi.fn(() => Promise.resolve({ ...PRIVACY, retentionDays: 90 }));
    renderAdmin(client({ setRetention }));

    const field = await screen.findByLabelText(/keep raw activity for/i);
    await userEvent.clear(field);
    await userEvent.type(field, "90");
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(setRetention).toHaveBeenCalledWith(WORKSPACE, 90);
    expect(await screen.findByRole("status")).toHaveTextContent(/kept for 90 days/i);
  });

  it("warns that shortening it deletes, before the change", async () => {
    renderAdmin();

    expect(await screen.findByText(/cannot be undone/i)).toBeVisible();
  });

  it("shows the region without pretending it can be changed", async () => {
    // Moving a workspace between regions is a data migration under compliance
    // pressure, and a dropdown that silently did nothing would be worse than
    // its absence.
    renderAdmin();

    expect(await screen.findByText(/us-central1/)).toBeVisible();
    expect(screen.getByText(/not self-service yet/i)).toBeVisible();
  });
});

describe("worker notification", () => {
  it("names who has not been shown it", async () => {
    // An obligation owed to each person before capture begins. An Owner who
    // cannot see who is outstanding cannot discharge it.
    renderAdmin();

    const list = await screen.findByRole("list", { name: /worker notification/i });
    expect(within(list).getByText("jo@example.com")).toBeVisible();
    expect(within(list).getByText(/not shown yet/i)).toBeVisible();
  });

  it("reports opt-outs as a number and names nobody", async () => {
    // **The decision this step turns on.** An opt-out is a person's own decision
    // about their own record; a list of names beside it is a list of employees
    // who declined to be recorded, handed to whoever writes their review.
    renderAdmin();

    expect(await screen.findByText(/1 person has switched off at least one source/i)).toBeVisible();
    expect(screen.getByText(/does not say who/i)).toBeVisible();
  });

  it("explains what happens to somebody who has not been shown it", async () => {
    // Not a warning about a broken product: it is the rule. CAIRN attributes
    // nothing to a person until they have seen what it reads.
    renderAdmin();

    expect(
      await screen.findByText(/does not\s+attribute it to them until they have/i),
    ).toBeVisible();
  });
});

describe("what a role is offered", () => {
  const VIEWER = {
    ...SESSION,
    workspaces: [{ ...SESSION.workspaces[0]!, role: "viewer" as const }],
  };

  function asViewer(): ReturnType<typeof createStubClient> {
    return client({ getSession: vi.fn(() => Promise.resolve(VIEWER)) });
  }

  it("shows a Viewer what is connected and what happens to their data", async () => {
    // Readable by everyone deliberately: these are facts about what happens to
    // the reader's own activity, and a person should not need a role to learn
    // them.
    renderAdmin(asViewer());

    expect(await screen.findByText(/never the contents of your code/i)).toBeVisible();
    expect(screen.getByLabelText(/keep raw activity for/i)).toBeDisabled();
  });

  it("offers a Viewer no control they would be refused", async () => {
    renderAdmin(asViewer());

    await screen.findByRole("list", { name: /members/i });
    expect(screen.queryByLabelText(/role for/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /disconnect/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
  });

  it("does not show a Viewer who has not been notified", async () => {
    // That screen names people, and whether a colleague has been notified is
    // compliance administration rather than something everyone needs.
    renderAdmin(asViewer());

    await screen.findByRole("list", { name: /members/i });
    expect(screen.queryByRole("list", { name: /worker notification/i })).not.toBeInTheDocument();
  });

  it("does not put a workspace link in a Viewer's navigation", async () => {
    renderAdmin(asViewer());

    const nav = await screen.findByRole("navigation", { name: /primary/i });
    expect(within(nav).queryByRole("link", { name: /^workspace$/i })).not.toBeInTheDocument();
    // Trust and privacy is for everybody, and its slot in the navigation is
    // deliberate: a page about what is recorded that somebody has to go looking
    // for is one they conclude was hidden.
    expect(within(nav).getByRole("link", { name: /trust and privacy/i })).toBeVisible();
  });

  it("passes an axe audit", async () => {
    const { container } = renderAdmin();
    await screen.findByRole("list", { name: /members/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("the trust and privacy centre", () => {
  const TRUST: Trust = {
    sources: [
      {
        source: "github",
        label: "GitHub",
        reads: "Commit messages, pull request titles and reviews. Never the contents of your code.",
        connected: true,
      },
      {
        source: "meeting",
        label: "Meetings",
        reads: "Transcripts of meetings your workspace connects. Never audio.",
        connected: false,
      },
    ],
    refusals: ["CAIRN never scores or ranks people."],
    commitments: [
      { title: "Everyone sees the same thing", detail: "Roles decide what you can configure." },
    ],
    retentionDays: 90,
    region: "us-central1",
    awaitingNotification: 2,
    subprocessors: [{ title: "Google Cloud (Vertex AI)", detail: "Runs the models." }],
  };

  function renderTrust(
    overrides = {},
    role: "owner" | "admin" | "member" | "viewer" = "owner",
  ): ReturnType<typeof renderRoute> {
    // The reader's role decides which controls are offered, so it has to be
    // settable per test. `SESSION` here is the harness's auth session, not the
    // support-session fixture further down.
    const authenticated = {
      ...SESSION,
      workspaces: [{ ...SESSION.workspaces[0]!, role }],
    };
    return renderRoute(
      <AppLayout>
        <TrustPage />
      </AppLayout>,
      {
        client: client({
          getSession: vi.fn(() => Promise.resolve(authenticated)),
          getTrust: vi.fn(() => Promise.resolve(TRUST)),
          ...overrides,
        }),
        route: "/trust",
      },
    );
  }

  it("states this workspace's own numbers", async () => {
    // A trust page quoting a retention period the product does not apply is the
    // most damaging sentence CAIRN could publish, because its whole audience is
    // people deciding whether the rest is true.
    renderTrust();

    expect(await screen.findByText(/90 days, then deleted/i)).toBeVisible();
    expect(screen.getByText(/us-central1/)).toBeVisible();
  });

  it("says which sources are switched on and which are not", async () => {
    renderTrust();

    expect(await screen.findByText(/^connected$/i)).toBeVisible();
    expect(screen.getByText(/^not connected$/i)).toBeVisible();
  });

  it("distinguishes raw activity from the team's record", async () => {
    renderTrust();

    expect(await screen.findByText(/messages and payloads cairn\s+received/i)).toBeVisible();
  });

  it("names its subprocessors rather than calling them partners", async () => {
    renderTrust();

    expect(await screen.findByText(/google cloud \(vertex ai\)/i)).toBeVisible();
    expect(screen.getByRole("main").textContent).not.toMatch(/trusted partners/i);
  });

  it("says how many people are still to be shown the notification", async () => {
    renderTrust();

    expect(await screen.findByText(/2 people have not been shown it yet/i)).toBeVisible();
  });

  it("carries no reassurance", async () => {
    // Every line is either checkable by using the product for an afternoon or a
    // name somebody can look up. "We take your privacy seriously" is the
    // sentence this asserts the absence of.
    renderTrust();

    await screen.findByRole("heading", { name: /what cairn reads/i });
    const main = await screen.findByRole("main");

    expect(main.textContent).not.toMatch(
      /take (your )?privacy seriously|industry.leading|bank.grade/i,
    );
  });

  it("passes an axe audit", async () => {
    const { container } = renderTrust();
    await screen.findByRole("heading", { name: /what cairn reads/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  describe("when CAIRN staff have looked", () => {
    const SUPPORT_SESSION: SupportSession = {
      id: "44444444-4444-4444-4444-444444444444",
      requestedBy: "sam@cairn.dev",
      reason: "investigating an integration failure",
      requestedScope: "configuration_diagnostics",
      approvedScope: "configuration_diagnostics",
      status: "approved",
      active: false,
      requestedMinutes: 40,
      requestedAt: "2026-08-12T09:00:00Z",
      decidedAt: "2026-08-12T09:04:00Z",
      decidedBy: "ali@acme.example.com",
      expiresAt: "2026-08-12T09:44:00Z",
      revokedAt: null,
      breakGlass: false,
      events: [
        {
          occurredAt: "2026-08-12T09:05:00Z",
          scope: "configuration_diagnostics",
          description: "Read 3 recorded activity statements",
        },
      ],
    };

    it("says nobody has looked, rather than saying nothing", async () => {
      // An absent section reads as an unanswered question. md/15 §5.2 wants the
      // customer able to check, including when the answer is "never".
      renderTrust();

      expect(
        await screen.findByText(/nobody at cairn has asked to look at this workspace/i),
      ).toBeVisible();
    });

    it("names who asked, why, and who decided", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      expect(await screen.findByText(/sam@cairn.dev asked on/i)).toBeVisible();
      expect(screen.getByText(/investigating an integration failure/i)).toBeVisible();
      expect(screen.getByText(/decided .* by ali@acme.example.com/i)).toBeVisible();
    });

    it("lists what was actually opened, not only what was permitted", async () => {
      // An approval is permission; the events are use. "Did they actually look"
      // is the question a customer is asking.
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      expect(await screen.findByText(/read 3 recorded activity statements/i)).toBeVisible();
    });

    it("distinguishes a live session from a finished one", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([{ ...SUPPORT_SESSION, active: true }])),
      });

      expect(await screen.findByText(/active now/i)).toBeVisible();
    });

    it("says a refusal was a refusal", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([{ ...SUPPORT_SESSION, status: "rejected" as const, active: false }]),
        ),
      });

      expect(await screen.findByText(/^refused$/i)).toBeVisible();
    });

    it("shows an Owner the controls for a pending request", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([{ ...SUPPORT_SESSION, status: "pending" as const, active: false }]),
        ),
      });

      expect(await screen.findByRole("button", { name: /allow/i })).toBeVisible();
      expect(screen.getByRole("button", { name: /refuse/i })).toBeVisible();
    });

    it("sends the decision", async () => {
      const decideSupportSession = vi.fn(() => Promise.resolve(SUPPORT_SESSION));
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([{ ...SUPPORT_SESSION, status: "pending" as const, active: false }]),
        ),
        decideSupportSession,
      });

      await userEvent.click(await screen.findByRole("button", { name: /allow/i }));

      expect(decideSupportSession).toHaveBeenCalledWith(WORKSPACE, SUPPORT_SESSION.id, true);
    });

    it("offers ending access while a session is live", async () => {
      const revokeSupportSession = vi.fn(() => Promise.resolve(SUPPORT_SESSION));
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([{ ...SUPPORT_SESSION, active: true }])),
        revokeSupportSession,
      });

      await userEvent.click(await screen.findByRole("button", { name: /end access now/i }));

      expect(revokeSupportSession).toHaveBeenCalledWith(WORKSPACE, SUPPORT_SESSION.id);
    });

    it.each(["member", "viewer"] as const)(
      "shows a %s the record and no controls",
      async (role) => {
        // Every member can read who looked at their workspace; deciding is an
        // Owner or Admin action, and a control that always fails teaches a
        // reader the product is broken.
        renderTrust(
          {
            listSupportSessions: vi.fn(() =>
              Promise.resolve([{ ...SUPPORT_SESSION, status: "pending" as const, active: false }]),
            ),
          },
          role,
        );

        expect(await screen.findByText(/sam@cairn.dev asked on/i)).toBeVisible();
        expect(screen.queryByRole("button", { name: /allow/i })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /refuse/i })).not.toBeInTheDocument();
      },
    );

    it("does not claim a revocation was the reader's doing", async () => {
      // "Ended by you" is false for every member who did not end it — including
      // the colleague reading the record afterwards.
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([
            {
              ...SESSION,
              status: "revoked" as const,
              active: false,
              revokedAt: "2026-08-12T09:20:00Z",
            },
          ]),
        ),
      });

      expect(await screen.findByText(/^ended early$/i)).toBeVisible();
      expect(screen.queryByText(/ended by you/i)).not.toBeInTheDocument();
    });

    it("states the approved scope, expiry and break-glass state", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      const entry = await screen.findByText(/approved for settings and diagnostics/i);
      expect(entry).toBeVisible();
      expect(entry).toHaveTextContent(/ends /i);
      // Break-glass is false, so the line must not appear at all rather than
      // saying "not emergency access".
      expect(screen.queryByText(/emergency access/i)).not.toBeInTheDocument();
    });

    it("says so when a decision cannot be recorded", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([{ ...SUPPORT_SESSION, status: "pending" as const, active: false }]),
        ),
        decideSupportSession: vi.fn(() => Promise.reject(apiError(422))),
      });

      await userEvent.click(await screen.findByRole("button", { name: /allow/i }));

      expect(await screen.findByRole("alert")).toBeVisible();
    });

    it("passes an axe audit with the controls on screen", async () => {
      const { container } = renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([{ ...SUPPORT_SESSION, status: "pending" as const, active: false }]),
        ),
      });
      await screen.findByRole("button", { name: /allow/i });

      await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
    });

    it("passes an axe audit with sessions on screen", async () => {
      const { container } = renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });
      await screen.findByRole("heading", { name: /when cairn staff have looked/i });

      await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
    });
  });
});
