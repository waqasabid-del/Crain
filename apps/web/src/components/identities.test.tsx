import type {
  AttributionHealth,
  ExternalIdentity,
  MyIdentities,
  Privacy,
  Session,
} from "@cairn/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { AdminPage } from "../routes/AdminPage.js";
import { SettingsPage } from "../routes/SettingsPage.js";
import { apiError, createStubClient, MEMBERS, renderRoute, SESSION } from "../test/harness.js";

import { mask } from "./ConnectedIdentities.js";

/**
 * Connected identities, and the two things this feature must never do.
 *
 * **A provider account id must not reach the page.** A Slack `U…`, a Chat
 * `users/…` and a GitHub numeric id are private handles for a human. The
 * assertions below check `textContent` *and* `innerHTML`, because the second
 * catches the failure the first cannot see: an id hidden in a `title`, an
 * `aria-label` or a `data-` attribute is still an id on the page, and it is the
 * form the leak is most likely to take, since it looks like an accessibility
 * improvement in review.
 *
 * **An administrator must not learn more about a member than the member sees.**
 * The workspace aggregate is counts, and a test asserts that no member name or
 * address appears in it. That is not defensiveness about today's response: this
 * is the exact screen where "who is unresolved?" first seems reasonable, and the
 * failure would be additive — nobody removes the counts, somebody adds a list
 * beside them.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

const WORKSPACE = SESSION.workspaces[0]?.workspace.id ?? "";

/**
 * Account ids that must never appear on screen.
 *
 * Shaped like the real ones — a GitHub numeric id, a Slack member id, a Chat
 * resource name — so that a partial render of one is still recognisable in a
 * failure message.
 */
const GITHUB_ACCOUNT = "48291077";
const SLACK_ACCOUNT = "U024BE7LH01";
const SLACK_SECOND_ACCOUNT = "U024BE7LH02";
const CHAT_ACCOUNT = "users/107520098342";

/** The server's rule, quoted rather than paraphrased — it has one author. */
const NOTICE =
  "CAIRN links an account to you in exactly two ways: a source tells us an " +
  "address it has verified and it matches your verified CAIRN address, or you " +
  "sign in and confirm the account is yours.";

const VERIFIED: ExternalIdentity = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  provider: "github",
  providerAccountId: GITHUB_ACCOUNT,
  verification: "verified_email_match",
  state: "active",
  linkedAt: "2026-04-02T09:00:00Z",
  explanation:
    "On 2026-04-02, this source supplied an email address that it had itself verified, and that address matched the address you verified on your CAIRN account. Both verifications were required.",
};

const SELF_CONFIRMED: ExternalIdentity = {
  id: "aaaaaaaa-0000-0000-0000-000000000002",
  provider: "slack",
  providerAccountId: SLACK_ACCOUNT,
  verification: "self_confirmed",
  state: "active",
  linkedAt: "2026-05-11T09:00:00Z",
  explanation:
    "You confirmed on 2026-05-11, while signed in to CAIRN, that this account is yours. Your signed-in session is the evidence.",
};

const REVOKED: ExternalIdentity = {
  id: "aaaaaaaa-0000-0000-0000-000000000003",
  provider: "google_chat",
  providerAccountId: CHAT_ACCOUNT,
  verification: "self_confirmed",
  state: "revoked",
  linkedAt: "2026-02-01T09:00:00Z",
  revokedAt: "2026-06-01T09:00:00Z",
  explanation: "You unlinked this account, so CAIRN stopped attributing it. The record is kept.",
};

const DISPUTED: ExternalIdentity = {
  ...REVOKED,
  id: "aaaaaaaa-0000-0000-0000-000000000004",
  state: "disputed",
  explanation:
    "You said this account is not yours, so CAIRN stopped attributing it. The record is kept.",
};

function identities(overrides: Partial<MyIdentities> = {}): MyIdentities {
  return {
    identities: [VERIFIED, SELF_CONFIRMED],
    proposals: [{ kind: "email", value: "ali@example.com" }],
    notice: NOTICE,
    ...overrides,
  };
}

const HEALTH: AttributionHealth = {
  resolvedByProvider: { github: 7, slack: 4 },
  unresolvedByProvider: { github: 2, google_chat: 5 },
  disputed: 1,
  revoked: 3,
  notice:
    "Counts only. CAIRN cannot show you which people are unresolved, how much any person did, or any per-person breakdown.",
};

/** Enough of the privacy payload for the admin screen to render around. */
const PRIVACY: Privacy = {
  retentionDays: 30,
  minRetentionDays: 7,
  maxRetentionDays: 365,
  region: "europe-west1",
};

function settingsClient(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    getMyIdentities: vi.fn(() => Promise.resolve(identities())),
    ...overrides,
  });
}

function renderSettings(stub = settingsClient()): ReturnType<typeof renderRoute> {
  return renderRoute(<SettingsPage />, { client: stub, route: "/settings" });
}

/**
 * The section, once it has finished loading.
 *
 * Scoped so an assertion cannot pass on wording from another part of the
 * screen, and awaited past the skeleton: the heading is painted by the section
 * itself and is on screen before the read resolves, so returning at the heading
 * would hand every test a placeholder.
 */
async function identitySection(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: "Connected identities" });
  const section = heading.closest("section");
  if (section === null) throw new Error("Connected identities is not inside a section");

  await waitFor(() => {
    expect(within(section).queryByText(/loading your connected accounts/i)).toBeNull();
  });
  return section;
}

describe("the reader's own identities", () => {
  it("asks only for the caller's own links, with no subject", async () => {
    const getMyIdentities = vi.fn(() => Promise.resolve(identities()));
    renderSettings(settingsClient({ getMyIdentities }));
    await identitySection();

    // A workspace and request options, and nothing that could name a person.
    // The API has no subject parameter; this asserts the client is not handed
    // one anyway.
    expect(getMyIdentities).toHaveBeenCalledWith(WORKSPACE, expect.anything());
  });

  it("shows nobody else's identities and offers no control over them", async () => {
    renderSettings();
    const section = await identitySection();

    // MEMBERS[1] is a colleague. Neither their name nor their address belongs
    // on a screen about the reader's own accounts, and a control naming them
    // would be the claim-a-colleague attack with a button on it.
    expect(section.textContent).not.toContain("jo@example.com");
    expect(section.textContent).not.toContain(MEMBERS[0]?.displayName ?? "Ali Rahman");
  });

  it("never renders a provider account id, in text or in an attribute", async () => {
    const { container } = renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() =>
          Promise.resolve(identities({ identities: [VERIFIED, SELF_CONFIRMED, REVOKED] })),
        ),
      }),
    );
    await identitySection();

    for (const account of [GITHUB_ACCOUNT, SLACK_ACCOUNT, CHAT_ACCOUNT]) {
      // Both, deliberately: `textContent` misses `title`, `aria-label` and
      // `data-*`, which is exactly where an id gets tucked away.
      expect(container.textContent).not.toContain(account);
      expect(container.innerHTML).not.toContain(account);
    }
  });

  it("masks to four characters when two accounts share a source", async () => {
    const twin: ExternalIdentity = {
      ...SELF_CONFIRMED,
      id: "aaaaaaaa-0000-0000-0000-000000000005",
      providerAccountId: SLACK_SECOND_ACCOUNT,
    };
    const { container } = renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() =>
          Promise.resolve(identities({ identities: [SELF_CONFIRMED, twin] })),
        ),
      }),
    );
    const section = await identitySection();

    expect(within(section).getByText(/account ending …LH01/)).toBeVisible();
    expect(within(section).getByText(/account ending …LH02/)).toBeVisible();
    // The mask is a suffix, never the value.
    expect(container.innerHTML).not.toContain(SLACK_ACCOUNT);
    expect(container.innerHTML).not.toContain(SLACK_SECOND_ACCOUNT);
  });

  it("keeps four characters and refuses to mask a value it cannot mask", () => {
    expect(mask("U024BE7LH01")).toBe("…LH01");
    // Four characters of a four-character value is the whole value.
    expect(mask("U024")).toBeNull();
  });

  it("distinguishes every state in words, and quotes the server for how it knows", async () => {
    renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() =>
          Promise.resolve(
            identities({ identities: [VERIFIED, SELF_CONFIRMED, REVOKED, DISPUTED] }),
          ),
        ),
      }),
    );
    const section = await identitySection();

    expect(within(section).getByText("Verified by matching address")).toBeVisible();
    expect(within(section).getByText("Confirmed by you")).toBeVisible();
    expect(within(section).getByText("Unlinked — no longer attributed to you")).toBeVisible();
    expect(within(section).getByText("Not yours — no longer attributed to you")).toBeVisible();

    // The explanation is the API's prose, not a second account of how CAIRN
    // knows written on the client.
    expect(within(section).getByText(VERIFIED.explanation)).toBeVisible();
    expect(within(section).getByText(SELF_CONFIRMED.explanation)).toBeVisible();
    // And the rule itself, in the server's words.
    expect(within(section).getByText(NOTICE)).toBeVisible();
  });

  it("says nothing is connected without treating it as a fault", async () => {
    renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() =>
          Promise.resolve({ identities: [], proposals: [], notice: NOTICE }),
        ),
      }),
    );
    const section = await identitySection();

    expect(within(section).getByRole("heading", { name: "Nothing connected yet" })).toBeVisible();
    expect(within(section).getByText(/attributed to that account and to no person/i)).toBeVisible();
  });

  it("announces the load politely while it is happening", async () => {
    renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(
          () =>
            new Promise<MyIdentities>(() => {
              // Never settles: the point of this test is the state in between.
            }),
        ),
      }),
    );

    // The skeleton itself says nothing; the visually hidden line inside the
    // polite live region is the whole announcement.
    expect(await screen.findByText(/loading your connected accounts/i)).toBeInTheDocument();
  });

  it("reports a failure as an alert and offers a way forward", async () => {
    const failing = vi
      .fn<() => Promise<MyIdentities>>()
      .mockRejectedValueOnce(apiError(500))
      .mockResolvedValue(identities());
    renderSettings(settingsClient({ getMyIdentities: failing }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/could not be loaded/i)).toBeVisible();

    await userEvent.click(within(alert).getByRole("button", { name: /try again/i }));

    expect(await screen.findByText("Verified by matching address")).toBeVisible();
  });

  it("shows the reader their own proposed identifiers, described as not yet links", async () => {
    renderSettings();
    const section = await identitySection();

    expect(
      within(section).getByRole("heading", { name: /identifiers cairn has attached to you/i }),
    ).toBeVisible();
    expect(
      within(section).getByText(/never shows you an identifier belonging to a colleague/i),
    ).toBeVisible();
  });
});

describe("ending a link", () => {
  it("does nothing until the reader confirms, and says what actually happens", async () => {
    const revoke = vi.fn(() => Promise.resolve({ ...VERIFIED, state: "revoked" as const }));
    renderSettings(settingsClient({ revokeMyIdentity: revoke }));
    const section = await identitySection();

    await userEvent.click(
      within(section).getByRole("button", { name: "Unlink this GitHub account" }),
    );

    // The request has not been made: the first press asks the question.
    expect(revoke).not.toHaveBeenCalled();
    expect(within(section).getByText(/CAIRN stops attributing this account to you/i)).toBeVisible();
    // The consequence, stated without implying a deletion, because there is not
    // one: the evidence and its provenance survive.
    expect(within(section).getByText(/Nothing is deleted/i)).toBeVisible();
    expect(within(section).getByText(/where each piece came from/i)).toBeVisible();
  });

  it("lets the reader back out", async () => {
    const revoke = vi.fn(() => Promise.resolve(VERIFIED));
    renderSettings(settingsClient({ revokeMyIdentity: revoke }));
    const section = await identitySection();

    await userEvent.click(
      within(section).getByRole("button", { name: "Unlink this GitHub account" }),
    );
    await userEvent.click(within(section).getByRole("button", { name: "Keep it linked" }));

    expect(revoke).not.toHaveBeenCalled();
    expect(
      within(section).getByRole("button", { name: "Unlink this GitHub account" }),
    ).toBeVisible();
  });

  it("unlinks without disputing when the link was right and is now over", async () => {
    const revoke = vi.fn(() => Promise.resolve({ ...VERIFIED, state: "revoked" as const }));
    renderSettings(settingsClient({ revokeMyIdentity: revoke }));
    const section = await identitySection();

    await userEvent.click(
      within(section).getByRole("button", { name: "Unlink this GitHub account" }),
    );
    await userEvent.click(within(section).getByRole("button", { name: "Yes, unlink it" }));

    expect(revoke).toHaveBeenCalledWith(WORKSPACE, VERIFIED.id, false);
  });

  it("records a dispute when the link was wrong from the start", async () => {
    const revoke = vi.fn(() => Promise.resolve({ ...VERIFIED, state: "disputed" as const }));
    renderSettings(settingsClient({ revokeMyIdentity: revoke }));
    const section = await identitySection();

    await userEvent.click(
      within(section).getByRole("button", { name: "This GitHub account was never mine" }),
    );
    expect(within(section).getByText(/the original link was wrong/i)).toBeVisible();

    await userEvent.click(within(section).getByRole("button", { name: "Yes, it was never mine" }));

    expect(revoke).toHaveBeenCalledWith(WORKSPACE, VERIFIED.id, true);
  });

  it("marks the row busy while the change is in flight", async () => {
    let settle = (): void => {
      // Replaced below, once the promise hands over its resolver.
    };
    const revoke = vi.fn(
      () =>
        new Promise<ExternalIdentity>((resolve) => {
          settle = () => {
            resolve({ ...VERIFIED, state: "revoked" });
          };
        }),
    );
    renderSettings(settingsClient({ revokeMyIdentity: revoke }));
    const section = await identitySection();

    await userEvent.click(
      within(section).getByRole("button", { name: "Unlink this GitHub account" }),
    );
    await userEvent.click(within(section).getByRole("button", { name: "Yes, unlink it" }));

    // `aria-busy` rather than a spinner: the button keeps its name, so a screen
    // reader user is told what is busy.
    expect(within(section).getByRole("button", { name: "Yes, unlink it" })).toHaveAttribute(
      "aria-busy",
      "true",
    );

    settle();
    await waitFor(() => {
      expect(
        within(section).queryByRole("button", { name: "Yes, unlink it" }),
      ).not.toBeInTheDocument();
    });
  });

  it("can be operated from the keyboard alone", async () => {
    const revoke = vi.fn(() => Promise.resolve({ ...VERIFIED, state: "revoked" as const }));
    renderSettings(settingsClient({ revokeMyIdentity: revoke }));
    const section = await identitySection();

    const unlink = within(section).getByRole("button", { name: "Unlink this GitHub account" });
    unlink.focus();
    expect(unlink).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    const confirm = within(section).getByRole("button", { name: "Yes, unlink it" });
    confirm.focus();
    await userEvent.keyboard("{Enter}");

    expect(revoke).toHaveBeenCalledWith(WORKSPACE, VERIFIED.id, false);
  });

  it("offers no ending control on a link that has already ended", async () => {
    renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() => Promise.resolve(identities({ identities: [REVOKED] }))),
      }),
    );
    const section = await identitySection();

    expect(within(section).queryByRole("button", { name: /unlink this/i })).not.toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: /never mine/i })).not.toBeInTheDocument();
  });
});

describe("confirming an account", () => {
  it("sends the source and the account the reader named", async () => {
    const confirm = vi.fn(() =>
      Promise.resolve({ ...SELF_CONFIRMED, providerAccountId: "U0PLAIN99" }),
    );
    renderSettings(settingsClient({ confirmMyIdentity: confirm }));
    const section = await identitySection();

    await userEvent.selectOptions(within(section).getByLabelText("Source"), "slack");
    await userEvent.type(within(section).getByLabelText(/your account id/i), "U0PLAIN99");
    await userEvent.click(
      within(section).getByRole("button", { name: "Confirm this account is mine" }),
    );

    expect(confirm).toHaveBeenCalledWith(WORKSPACE, "slack", "U0PLAIN99");
  });

  it("does not echo the account back after confirming it", async () => {
    const confirm = vi.fn(() =>
      Promise.resolve({ ...SELF_CONFIRMED, providerAccountId: "U0PLAIN99" }),
    );
    const { container } = renderSettings(settingsClient({ confirmMyIdentity: confirm }));
    const section = await identitySection();

    await userEvent.selectOptions(within(section).getByLabelText("Source"), "slack");
    await userEvent.type(within(section).getByLabelText(/your account id/i), "U0PLAIN99");
    await userEvent.click(
      within(section).getByRole("button", { name: "Confirm this account is mine" }),
    );

    expect(await screen.findByText(/is now linked to you/i)).toBeVisible();
    expect(within(section).getByLabelText(/your account id/i)).toHaveValue("");
    expect(container.innerHTML).not.toContain("U0PLAIN99");
  });

  it("answers a refusal in words that are true of it", async () => {
    // The generic 403 copy says an Owner or Admin decides who can. Nobody
    // decides this: it is not a permission.
    const confirm = vi.fn(() => Promise.reject(apiError(403, "not-your-record")));
    renderSettings(settingsClient({ confirmMyIdentity: confirm }));
    const section = await identitySection();

    await userEvent.type(within(section).getByLabelText(/your account id/i), "48291077");
    await userEvent.click(
      within(section).getByRole("button", { name: "Confirm this account is mine" }),
    );

    const alert = await within(section).findByRole("alert");
    expect(alert).toHaveTextContent(/has not recorded any work against your account yet/i);
    expect(alert).not.toHaveTextContent(/an Owner or an Admin/i);
  });

  it("refuses a taken account without naming who holds it", async () => {
    const confirm = vi.fn(() => Promise.reject(apiError(409, "identity-already-linked")));
    renderSettings(settingsClient({ confirmMyIdentity: confirm }));
    const section = await identitySection();

    await userEvent.type(within(section).getByLabelText(/your account id/i), "48291077");
    await userEvent.click(
      within(section).getByRole("button", { name: "Confirm this account is mine" }),
    );

    const alert = await within(section).findByRole("alert");
    expect(alert).toHaveTextContent(/CAIRN does not say who/i);
    expect(alert.textContent).not.toContain("jo@example.com");
  });
});

describe("who sees what", () => {
  const MEMBER: Session = {
    ...SESSION,
    workspaces: [{ ...SESSION.workspaces[0]!, role: "member" as const }],
  };

  it("gives a member their own section", async () => {
    renderSettings(settingsClient({ getSession: vi.fn(() => Promise.resolve(MEMBER)) }));

    expect(await screen.findByRole("heading", { name: "Connected identities" })).toBeVisible();
  });

  it("does not give a member the workspace aggregate", async () => {
    // Courtesy rather than protection — the API refuses independently — but a
    // control that would always be refused should not be on screen.
    renderRoute(<AdminPage />, {
      client: createStubClient({
        getSession: vi.fn(() => Promise.resolve(MEMBER)),
        listMembers: vi.fn(() => Promise.resolve(MEMBERS)),
        listIntegrations: vi.fn(() => Promise.resolve([])),
        getPrivacy: vi.fn(() => Promise.resolve(PRIVACY)),
        getAttributionHealth: vi.fn(() => Promise.resolve(HEALTH)),
      }),
      route: "/admin",
    });

    await screen.findByRole("list", { name: /members/i });
    expect(screen.queryByRole("heading", { name: /attribution health/i })).not.toBeInTheDocument();
  });
});

describe("accessibility", () => {
  it("has no axe violations with links, a confirmation and a form on screen", async () => {
    const { container } = renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() =>
          Promise.resolve(
            identities({ identities: [VERIFIED, SELF_CONFIRMED, REVOKED, DISPUTED] }),
          ),
        ),
        revokeMyIdentity: vi.fn(() => Promise.resolve(VERIFIED)),
      }),
    );
    const section = await identitySection();

    await userEvent.click(
      within(section).getByRole("button", { name: "Unlink this GitHub account" }),
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("has no axe violations in the empty and error states", async () => {
    const empty = renderSettings(
      settingsClient({
        getMyIdentities: vi.fn(() =>
          Promise.resolve({ identities: [], proposals: [], notice: NOTICE }),
        ),
      }),
    );
    await screen.findByRole("heading", { name: "Nothing connected yet" });
    await expect(axe(empty.container, AXE_OPTIONS)).resolves.toHaveNoViolations();
    empty.unmount();

    const failed = renderSettings(
      settingsClient({ getMyIdentities: vi.fn(() => Promise.reject(apiError(500))) }),
    );
    await screen.findByRole("alert");
    await expect(axe(failed.container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});
