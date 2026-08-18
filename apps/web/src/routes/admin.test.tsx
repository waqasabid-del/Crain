import type {
  AttributionHealth,
  GoogleChatDisconnect,
  GoogleChatInstall,
  GoogleChatSpaceList,
  GoogleChatSpaceSelection,
  GoogleMeetDisconnect,
  GoogleMeetInstall,
  Integration,
  Notifications,
  Privacy,
  SlackChannelList,
  SlackChannelSelection,
  SlackDisconnect,
  SlackInstall,
  SupportSession,
  Trust,
} from "@cairn/api-client";
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

/**
 * The `/invite` requirement in the server's own words.
 *
 * Copied from the API's `BOT_INVITE_NOTICE` rather than paraphrased. Every Slack
 * response carries it so that the sentence has one author, and a test matching a
 * paraphrase would keep passing on the day the backend changed what it says.
 */
const NOTICE =
  "CAIRN only receives messages from channels the CAIRN app has been added to. " +
  "For each channel you select, run /invite @CAIRN in Slack. CAIRN cannot add " +
  "itself — it does not ask Slack for permission to join channels.";

/** What `PUT /channels` answers with: IDs, and no names at all. */
function SAVED(channelIds: string[]): SlackChannelSelection {
  return { channelIds, notice: NOTICE };
}

const DISCONNECTED: SlackDisconnect = {
  state: "disconnected",
  disconnectedAt: "2026-08-17T09:00:00Z",
  credentialCleared: true,
  retentionNotice:
    "Slack will stop being collected from immediately, and the stored access token has been destroyed.",
};

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

/**
 * Attribution, in counts and nothing else.
 *
 * Every field the response has is here, which is the point worth stating: there
 * is no field on it that could carry a name, an id, an address or a measure of
 * anybody's activity, so the screen below has nothing per-person to withhold.
 */
const HEALTH: AttributionHealth = {
  resolvedByProvider: { github: 7, slack: 4 },
  unresolvedByProvider: { github: 2, google_chat: 5 },
  disputed: 1,
  revoked: 3,
  notice:
    "Counts only. CAIRN cannot show you which people are unresolved, how much " +
    "any person did, or any per-person breakdown. Attribution health is a " +
    "question about connections, not about colleagues.",
};

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMembers: vi.fn(() => Promise.resolve(MEMBERS)),
    listIntegrations: vi.fn(() => Promise.resolve(INTEGRATIONS)),
    getPrivacy: vi.fn(() => Promise.resolve(PRIVACY)),
    getNotifications: vi.fn(() => Promise.resolve(NOTIFICATIONS)),
    getAttributionHealth: vi.fn(() => Promise.resolve(HEALTH)),
    ...overrides,
  });
}

function renderAdmin(stub = client(), search = ""): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <AdminPage />
    </AppLayout>,
    { client: stub, route: "/admin", search },
  );
}

/**
 * The card for one source.
 *
 * Two are listed now — GitHub, and Slack whether or not it is connected — so an
 * assertion that does not say which one it means can pass for the wrong reason,
 * or fail because the sentence it wanted is on screen twice.
 */
function card(name: RegExp): HTMLElement {
  const article = screen.getByRole("heading", { name }).closest("article");
  if (article === null) throw new Error("that heading is not inside a connection card");
  return article;
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

  it("shows each connection as a record, not a toggle", async () => {
    renderAdmin();

    const connections = await screen.findByRole("list", { name: /connected sources/i });
    expect(within(connections).getByRole("heading", { name: /github — acme-inc/i })).toBeVisible();
    // The state as a word. Never a colour, and never a dot.
    expect(within(connections).getByText("Connected")).toBeVisible();
    expect(within(connections).getByText("Authorised on")).toBeVisible();
  });

  it("omits the details the API does not return, and says that it does", async () => {
    // **The commitment this screen turns on.** The Trust page's whole claim is
    // that its numbers are read from the workspace; a plausible "Last synced 4
    // minutes ago" invented from a field the server never sent would discredit
    // every other line on it. The sentence is asserted alongside the absence,
    // because an omitted row on its own reads as "fine" rather than "not
    // recorded".
    renderAdmin();

    const connections = await screen.findByRole("list", { name: /connected sources/i });
    expect(within(connections).queryByText("Last successful sync")).not.toBeInTheDocument();
    expect(within(connections).queryByText("Access granted")).not.toBeInTheDocument();
    expect(screen.getByText(/left out rather than guessed at/i)).toBeVisible();
  });

  it("asks before disconnecting, states the effect, and only then calls the client", async () => {
    const disconnectGitHub = vi.fn(() => Promise.resolve());
    renderAdmin(client({ disconnectGitHub }));

    await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));
    expect(disconnectGitHub).not.toHaveBeenCalled();
    expect(screen.getByText(/stops cairn reading anything more from acme-inc/i)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: /disconnect github/i }));

    expect(disconnectGitHub).toHaveBeenCalledWith(WORKSPACE, 42);
  });

  it("says so when a disconnect is refused", async () => {
    renderAdmin(client({ disconnectGitHub: vi.fn(() => Promise.reject(apiError(403))) }));

    await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));
    await userEvent.click(screen.getByRole("button", { name: /disconnect github/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/does not have access to that/i);
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

  it("shows a skeleton the size of the cards it is waiting for", async () => {
    // A skeleton announces nothing on its own, so the announcement is the test:
    // the boxes exist to stop the page jumping, not to inform anybody.
    // A request that never settles, so the skeleton stays on screen.
    const pending = new Promise<Integration[]>(() => {
      /* never resolves */
    });
    renderAdmin(client({ listIntegrations: vi.fn(() => pending) }));

    expect(await screen.findByText(/loading the connected sources/i)).toBeInTheDocument();
  });

  it("says nothing is connected, and lists what each source would ask for anyway", async () => {
    // Not an empty panel: the sources are listed switched off, so somebody can
    // read what connecting one would permit while the answer is still "no".
    renderAdmin(client({ listIntegrations: vi.fn(() => Promise.resolve([])) }));

    expect(await screen.findByText(/captures nothing until a source is connected/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: /^slack$/i })).toBeVisible();
    expect(screen.getByText("channels:history")).toBeVisible();
  });

  it("offers a safe retry when the list could not be loaded", async () => {
    const listIntegrations = vi
      .fn<() => Promise<Integration[]>>()
      .mockRejectedValueOnce(apiError(503))
      .mockResolvedValue(INTEGRATIONS);
    renderAdmin(client({ listIntegrations }));

    expect(await screen.findByText(/the connected sources could not be loaded/i)).toBeVisible();
    await userEvent.click(screen.getAllByRole("button", { name: /try again/i })[0]!);

    expect(await screen.findByRole("heading", { name: /github — acme-inc/i })).toBeVisible();
  });

  it("answers a permission refusal rather than reporting a generic failure", async () => {
    renderAdmin(client({ listIntegrations: vi.fn(() => Promise.reject(apiError(403))) }));

    expect(await screen.findByText(/does not have access to that/i)).toBeVisible();
  });

  it("restores focus to the control when the confirmation is dismissed", async () => {
    // Cancelling must not drop a keyboard reader at the top of the document,
    // several sections above where they were working.
    renderAdmin();

    await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));
    await userEvent.click(screen.getByRole("button", { name: /keep it connected/i }));

    expect(screen.getByRole("button", { name: /^disconnect$/i })).toHaveFocus();
  });

  it("passes an axe audit with the confirmation open", async () => {
    const { container } = renderAdmin();

    await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

/**
 * Slack: the connect half.
 *
 * Two things here are not ordinary integration plumbing and are why this block
 * is long.
 *
 * - **The bot only receives messages from public channels it has been invited
 *   to.** CAIRN does not request `channels:join`, so a channel selected here and
 *   never `/invite`d stays silent forever. If the screen does not say so,
 *   somebody selects four channels, sees nothing arrive, and concludes the
 *   product is broken — and from the screen alone they would be right to.
 * - **A denial is a legitimate answer, not a failure.** Somebody was asked for
 *   permission and said no. An apology and an alert would teach them that
 *   declining broke something, which is how people learn to stop reading consent
 *   screens.
 */
describe("connecting Slack", () => {
  const SLACK: Integration = {
    source: "slack",
    account: "Northwind HQ",
    installationId: 7,
    connectedAt: "2026-07-02T09:00:00Z",
    disconnectedAt: null,
    suspended: false,
  };

  const CHANNELS: SlackChannelList = {
    channels: [
      { id: "C001", name: "general", botIsMember: true, selected: true },
      { id: "C002", name: "engineering", botIsMember: false, selected: false },
    ],
    notice: NOTICE,
  };

  const INSTALL: SlackInstall = {
    authorizeUrl: "https://slack.com/oauth/v2/authorize?state=nonce",
    expiresAt: "2026-08-17T10:15:00Z",
    requestedScopes: ["channels:history", "channels:read", "users:read"],
    notice: NOTICE,
  };

  /** A workspace with Slack connected, and every Slack endpoint stubbed. */
  function slackClient(overrides = {}): ReturnType<typeof createStubClient> {
    return client({
      listIntegrations: vi.fn(() => Promise.resolve([SLACK])),
      startSlackInstall: vi.fn(() => Promise.resolve(INSTALL)),
      listSlackChannels: vi.fn(() => Promise.resolve(CHANNELS)),
      setSlackChannels: vi.fn(() => Promise.resolve(SAVED(["C001"]))),
      disconnectSlack: vi.fn(() => Promise.resolve(DISCONNECTED)),
      ...overrides,
    });
  }

  /** Slack not yet connected. */
  function unconnectedClient(overrides = {}): ReturnType<typeof createStubClient> {
    return slackClient({
      listIntegrations: vi.fn(() => Promise.resolve(INTEGRATIONS)),
      ...overrides,
    });
  }

  /**
   * A window whose navigation can be observed.
   *
   * `location.assign` is what actually sends somebody to Slack, and jsdom
   * neither performs nor records it. Stubbing the whole object rather than
   * spying on the method because `window.location` is not configurable.
   */
  function captureNavigation(): ReturnType<typeof vi.fn> {
    const assign = vi.fn();
    const { href, origin, pathname, search } = window.location;
    vi.stubGlobal("location", { href, origin, pathname, search, assign });
    return assign;
  }

  describe("what the reader is told before they authorise anything", () => {
    it("names the three scopes exactly, in both the literal form and plain words", async () => {
      // The literal string is what somebody can check against Slack's own
      // consent screen; the sentence is what they can understand. A paraphrase
      // on its own asks them to trust the translation.
      renderAdmin(unconnectedClient());

      await screen.findByRole("heading", { name: /^slack$/i });
      const slack = within(card(/^slack$/i));

      expect(slack.getByText("channels:history")).toBeVisible();
      expect(slack.getByText("channels:read")).toBeVisible();
      expect(slack.getByText("users:read")).toBeVisible();
      expect(slack.getByText(/read the messages in the public channels/i)).toBeVisible();
      expect(slack.getByText(/list this workspace's public channels/i)).toBeVisible();
      expect(slack.getByText(/look up who wrote a message/i)).toBeVisible();
    });

    it("asks for no fourth scope", async () => {
      // Locked deliberately. The day somebody adds a scope to the manifest this
      // fails, and whoever added it has to come and write the sentence that
      // explains it to a customer.
      renderAdmin(unconnectedClient());

      await screen.findByRole("heading", { name: /^slack$/i });
      const scopes = within(card(/^slack$/i)).getAllByText(/^[a-z]+:[a-z]+$/);

      expect(scopes.map((node) => node.textContent)).toEqual([
        "channels:history",
        "channels:read",
        "users:read",
      ]);
    });

    it("states what CAIRN cannot do, rather than leaving it to be inferred", async () => {
      // A list of granted permissions asks the reader to work out the complement
      // of a set whose size they do not know, and everybody's guess is "probably
      // more than that".
      renderAdmin(unconnectedClient());

      await screen.findByRole("heading", { name: /^slack$/i });
      const slack = within(card(/^slack$/i));

      expect(slack.getByText(/no permission to write anything to slack/i)).toBeVisible();
      expect(slack.getByText(/direct messages, private channels, or group dms/i)).toBeVisible();
      expect(slack.getByText(/does not request channels:join/i)).toBeVisible();
    });

    it("states the invite rule before anybody authorises anything", async () => {
      // **The single most important sentence on the screen.**
      renderAdmin(unconnectedClient());

      expect(
        await screen.findByText(/somebody has to run \/invite @CAIRN in that channel in slack/i),
      ).toBeVisible();
    });
  });

  describe("starting the connection", () => {
    it("asks the API where to send the customer, then sends them there", async () => {
      // **Why this is a button and not a link.** The install endpoint mints a
      // single-use `state` nonce and *returns* the authorise URL rather than
      // redirecting to it: a 302 on a credentialed request is followed by
      // `fetch`, not by the window, so the customer would never reach Slack's
      // consent screen at all. So the page asks, then navigates.
      const assign = captureNavigation();
      const startSlackInstall = vi.fn(() => Promise.resolve(INSTALL));
      renderAdmin(unconnectedClient({ startSlackInstall }));

      await userEvent.click(await screen.findByRole("button", { name: /^connect slack$/i }));

      expect(startSlackInstall).toHaveBeenCalledWith(WORKSPACE);
      expect(assign).toHaveBeenCalledWith(INSTALL.authorizeUrl);
    });

    it("says when the link it just minted stops working", async () => {
      // A `state` nonce is single-use and time-boxed. Somebody who opens the
      // consent screen, goes to lunch and comes back gets a failure whose only
      // available explanation is this sentence.
      captureNavigation();
      renderAdmin(unconnectedClient());

      await userEvent.click(await screen.findByRole("button", { name: /^connect slack$/i }));

      expect(await screen.findByText(/this link stops working at/i)).toBeVisible();
    });

    it("says so when the install could not even be started", async () => {
      // Slack unconfigured on the deployment answers 503. Navigating anyway
      // would send somebody to a URL that does not exist; saying nothing would
      // leave them pressing a button that appears to do nothing at all.
      const assign = captureNavigation();
      renderAdmin(
        unconnectedClient({ startSlackInstall: vi.fn(() => Promise.reject(apiError(503))) }),
      );

      await userEvent.click(await screen.findByRole("button", { name: /^connect slack$/i }));

      expect(await screen.findByRole("alert")).toBeVisible();
      expect(assign).not.toHaveBeenCalled();
    });

    it("names the act Reconnect when the grant has stopped working", async () => {
      // "Connect" on a source that was already on hides from the reader that it
      // ever was, and with it the question of what happened to it.
      renderAdmin(
        slackClient({
          listIntegrations: vi.fn(() => Promise.resolve([{ ...SLACK, suspended: true }])),
        }),
      );

      expect(await screen.findByRole("button", { name: /reconnect slack/i })).toBeVisible();
    });

    it("does not blame GitHub for a Slack failure", async () => {
      renderAdmin(
        slackClient({
          listIntegrations: vi.fn(() => Promise.resolve([{ ...SLACK, suspended: true }])),
        }),
      );

      await screen.findByRole("heading", { name: /slack — northwind hq/i });
      expect(
        within(card(/slack — northwind hq/i)).getByText(/slack has stopped accepting/i),
      ).toBeVisible();
      expect(screen.queryByText(/suspended on github/i)).not.toBeInTheDocument();
    });

    it("offers a Viewer no connect control, and says who has one", async () => {
      const viewer = unconnectedClient({
        getSession: vi.fn(() =>
          Promise.resolve({
            ...SESSION,
            workspaces: [{ ...SESSION.workspaces[0]!, role: "viewer" as const }],
          }),
        ),
      });
      renderAdmin(viewer);

      await screen.findByRole("heading", { name: /^slack$/i });
      const slack = within(card(/^slack$/i));

      expect(slack.queryByRole("button", { name: /^connect slack$/i })).not.toBeInTheDocument();
      // Absence is not an explanation.
      expect(
        slack.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
      ).toBeVisible();
      // And they can still read exactly what it would ask for.
      expect(slack.getByText("channels:history")).toBeVisible();
    });
  });

  describe("coming back from Slack's consent screen", () => {
    it("says plainly that it worked, and that nothing is being read yet", async () => {
      renderAdmin(slackClient(), "slack=connected");

      expect(await screen.findByText(/slack is connected/i)).toBeVisible();
      expect(screen.getByText(/only after the cairn app has been invited/i)).toBeVisible();
    });

    it("treats a denial as an answer, not as a failure", async () => {
      // **The decision this block turns on.** Somebody was asked for permission
      // and said no. `role="alert"`, an apology, or the word "failed" would tell
      // them their deliberate decision broke the product.
      renderAdmin(unconnectedClient(), "slack=denied");

      await screen.findByRole("heading", { name: /^slack$/i });
      const slackCard = card(/^slack$/i);
      const slack = within(slackCard);

      expect(slack.getByText(/nothing was connected/i)).toBeVisible();
      expect(slack.getByText(/you can start again whenever you want to/i)).toBeVisible();
      expect(slack.queryByRole("alert")).not.toBeInTheDocument();
      expect(slackCard.textContent).not.toMatch(/sorry|failed|went wrong/i);
    });

    it("reports a genuine failure as one, and says nothing was connected", async () => {
      // After a broken OAuth round trip the one thing somebody cannot tell from
      // the screen is whether access was granted anyway.
      renderAdmin(unconnectedClient(), "slack=error");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        /did not finish authorising cairn, so nothing was connected/i,
      );
    });

    it("ignores a return value it does not recognise", async () => {
      // The parameter is attacker-controllable, and rendering an arbitrary one
      // would put a stranger's words on a page whose whole point is that its
      // words are CAIRN's.
      renderAdmin(unconnectedClient(), "slack=<script>");

      await screen.findByRole("heading", { name: /^slack$/i });
      expect(screen.queryByText(/nothing was connected/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("choosing channels", () => {
    it("shows the selection the backend confirmed", async () => {
      renderAdmin(slackClient());

      expect(await screen.findByText(/cairn is reading 1 channel: #general\./i)).toBeVisible();
    });

    it("sends the whole new selection, not just the change", async () => {
      // `PUT` replaces rather than merges, so unchecking a box has to arrive as
      // an absence — and an absence only means anything when everything still
      // chosen is present alongside it.
      const setSlackChannels = vi.fn(() => Promise.resolve(SAVED(["C001", "C002"])));
      renderAdmin(slackClient({ setSlackChannels }));

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));
      await userEvent.click(screen.getByRole("checkbox", { name: /engineering/i }));

      expect(setSlackChannels).toHaveBeenCalledWith(WORKSPACE, ["C001", "C002"]);
    });

    it("ticks what the save confirmed, which is IDs and no names", async () => {
      // The response carries `channelIds` only, deliberately: names belong to
      // `conversations.list` and not to a write endpoint. The tick still has to
      // come from that answer, so it is folded back onto the channels the GET
      // described rather than taken from the click.
      renderAdmin(slackClient({ setSlackChannels: vi.fn(() => Promise.resolve(SAVED(["C002"]))) }));

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));
      await userEvent.click(screen.getByRole("checkbox", { name: /engineering/i }));

      expect(await screen.findByRole("checkbox", { name: /engineering/i })).toBeChecked();
      // And #general, which the server did *not* confirm, loses its tick: the
      // request was the full state of the checkboxes, so a missing ID is
      // permission withdrawn rather than a channel the server forgot.
      expect(screen.getByRole("checkbox", { name: /general/i })).not.toBeChecked();
      expect(screen.getByText(/cairn is reading 1 channel: #engineering\./i)).toBeVisible();
    });

    it("says which channels the app is not in, because those deliver nothing", async () => {
      // The single most common reason somebody connects Slack and sees nothing
      // arrive. CAIRN asks for no `channels:join`, so this is unanswerable from
      // any other part of the screen.
      renderAdmin(slackClient());

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));

      expect(screen.getByRole("checkbox", { name: /engineering/i })).toHaveAccessibleDescription(
        /the cairn app is not in this channel/i,
      );
    });

    it("prints the server's invite sentence rather than a second copy of it", async () => {
      renderAdmin(slackClient());

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));

      expect(screen.getByText(NOTICE)).toBeVisible();
    });

    it("only ticks a channel once the server has confirmed it", async () => {
      // **The commitment this screen turns on.** A tick is a claim that CAIRN is
      // reading that room. A request that never settles, so the answer never
      // arrives.
      const pending = new Promise<never>(() => {
        /* never resolves */
      });
      renderAdmin(slackClient({ setSlackChannels: vi.fn(() => pending) }));

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));
      await userEvent.click(screen.getByRole("checkbox", { name: /engineering/i }));

      const engineering = screen.getByRole("checkbox", { name: /engineering/i });
      expect(engineering).not.toBeChecked();
      expect(engineering).toHaveAttribute("aria-busy", "true");
    });

    it("leaves the checkbox where it was when the save is refused, and says why", async () => {
      renderAdmin(slackClient({ setSlackChannels: vi.fn(() => Promise.reject(apiError(403))) }));

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));
      await userEvent.click(screen.getByRole("checkbox", { name: /engineering/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/does not have access to that/i);
      expect(screen.getByRole("checkbox", { name: /engineering/i })).not.toBeChecked();
    });

    it("filters the channels by a search", async () => {
      renderAdmin(slackClient());

      await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));
      await userEvent.type(screen.getByRole("searchbox", { name: /search channels/i }), "eng");

      expect(screen.getByRole("checkbox", { name: /engineering/i })).toBeVisible();
      expect(screen.queryByRole("checkbox", { name: /general/i })).not.toBeInTheDocument();
    });

    it("shows a skeleton the size of what it is waiting for", async () => {
      const pending = new Promise<never>(() => {
        /* never resolves */
      });
      renderAdmin(slackClient({ listSlackChannels: vi.fn(() => pending) }));

      expect(await screen.findByText(/loading the slack channels/i)).toBeInTheDocument();
    });

    it("answers a permission refusal on the channel list rather than reporting a generic failure", async () => {
      renderAdmin(slackClient({ listSlackChannels: vi.fn(() => Promise.reject(apiError(403))) }));

      expect(await screen.findByText(/the slack channels could not be loaded/i)).toBeVisible();
      expect(screen.getByText(/does not have access to that/i)).toBeVisible();
    });

    it("offers a safe retry when the channel list could not be loaded", async () => {
      const listSlackChannels = vi
        .fn<() => Promise<SlackChannelList>>()
        .mockRejectedValueOnce(apiError(503))
        .mockResolvedValue(CHANNELS);
      renderAdmin(slackClient({ listSlackChannels }));

      await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

      expect(await screen.findByText(/cairn is reading 1 channel: #general\./i)).toBeVisible();
    });

    it("shows a Viewer which channels are read, read-only", async () => {
      const viewer = slackClient({
        getSession: vi.fn(() =>
          Promise.resolve({
            ...SESSION,
            workspaces: [{ ...SESSION.workspaces[0]!, role: "viewer" as const }],
          }),
        ),
      });
      renderAdmin(viewer);

      expect(await screen.findByText(/cairn is reading 1 channel: #general\./i)).toBeVisible();
      expect(screen.queryByRole("button", { name: /choose channels/i })).not.toBeInTheDocument();
      expect(
        screen.getByText(/an owner or an admin of this workspace chooses which channels/i),
      ).toBeVisible();
    });
  });

  describe("disconnecting", () => {
    it("states all three consequences before it does anything", async () => {
      // Collection stops, the credential is destroyed, and what was recorded is
      // *not* deleted — it follows retention like everything else. Deleting it is
      // a different request, and not a side effect of a button labelled
      // Disconnect.
      const disconnectSlack = vi.fn(() => Promise.resolve(DISCONNECTED));
      renderAdmin(slackClient({ disconnectSlack }));

      await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));

      expect(disconnectSlack).not.toHaveBeenCalled();
      expect(screen.getByText(/stops new collection immediately/i)).toBeVisible();
      expect(screen.getByText(/deletes the credential cairn stored/i)).toBeVisible();
      expect(screen.getByText(/removed on this workspace's retention schedule/i)).toBeVisible();
    });

    it("only disconnects once the reader has confirmed", async () => {
      // `POST .../disconnect`, not `DELETE`: it answers with what it did — the
      // credential cleared, and the retention that is deliberately unaffected.
      const disconnectSlack = vi.fn(() => Promise.resolve(DISCONNECTED));
      renderAdmin(slackClient({ disconnectSlack }));

      await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));
      await userEvent.click(screen.getByRole("button", { name: /disconnect slack/i }));

      expect(disconnectSlack).toHaveBeenCalledWith(WORKSPACE);
    });

    it("says so when a disconnect is refused", async () => {
      renderAdmin(slackClient({ disconnectSlack: vi.fn(() => Promise.reject(apiError(403))) }));

      await userEvent.click(await screen.findByRole("button", { name: /^disconnect$/i }));
      await userEvent.click(screen.getByRole("button", { name: /disconnect slack/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/does not have access to that/i);
    });
  });

  it("passes an axe audit with the picker open", async () => {
    const { container } = renderAdmin(slackClient(), "slack=connected");

    await userEvent.click(await screen.findByRole("button", { name: /choose channels/i }));

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit on the OAuth error return", async () => {
    const { container } = renderAdmin(unconnectedClient(), "slack=error");
    await screen.findByRole("alert");

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
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

  it("shows a Viewer the connection record and tells them who can change it", async () => {
    // Absence is not an explanation. Silence leaves a Viewer unable to tell
    // "not mine to do" from "nobody has done it", and the record itself is
    // theirs to read because it is about their own activity.
    renderAdmin(asViewer());

    await screen.findByRole("heading", { name: /github — acme-inc/i });
    const github = within(card(/github — acme-inc/i));

    expect(github.getByText("Connected")).toBeVisible();
    expect(
      github.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /disconnect/i })).not.toBeInTheDocument();
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
    // The Trust Center is for everybody, and its slot in the navigation is
    // deliberate: a page about what is recorded that somebody has to go looking
    // for is one they conclude was hidden.
    expect(within(nav).getByRole("link", { name: /trust center/i })).toBeVisible();
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

  it("lists the connections this workspace actually has, read-only", async () => {
    // The catalogue above says what CAIRN *could* read. This is the workspace's
    // own record — the difference between "we only read what you allow" and a
    // reader being able to check it.
    renderTrust();

    const connections = await screen.findByRole("list", { name: /connections/i });
    expect(within(connections).getByRole("heading", { name: /github — acme-inc/i })).toBeVisible();
    expect(within(connections).queryByRole("button", { name: /disconnect/i })).toBeNull();
  });

  it("tells an Owner where the connection is changed, since it is not changed here", async () => {
    // Read-only for everybody, Owners included: this page is the record and the
    // workspace screen is the control. A record with no explanation of where it
    // is changed reads as one nobody can change.
    renderTrust({}, "owner");

    await screen.findByRole("heading", { name: /github — acme-inc/i });
    expect(
      within(card(/github — acme-inc/i)).getByText(/disconnect this in workspace settings/i),
    ).toBeVisible();
  });

  it("invents no connection detail the API did not send", async () => {
    // The page's entire claim is that its numbers are read from the workspace.
    renderTrust();

    const connections = await screen.findByRole("list", { name: /connections/i });
    expect(within(connections).queryByText("Last successful sync")).not.toBeInTheDocument();
    expect(within(connections).queryByText("Access granted")).not.toBeInTheDocument();
  });

  describe("what it says about Slack", () => {
    const SLACK: Integration = {
      source: "slack",
      account: "Northwind HQ",
      installationId: 7,
      connectedAt: "2026-07-02T09:00:00Z",
      disconnectedAt: null,
      suspended: false,
    };

    function withSlack(payload: SlackChannelList, integrations: Integration[] = [SLACK]): object {
      return {
        listIntegrations: vi.fn(() => Promise.resolve(integrations)),
        listSlackChannels: vi.fn(() => Promise.resolve(payload)),
      };
    }

    it("states Slack's state whether or not it is connected", async () => {
      renderTrust();

      await screen.findByRole("heading", { name: /^slack$/i });
      expect(within(card(/^slack$/i)).getByText("Disconnected")).toBeVisible();
    });

    it("lists the channels the backend returned, as a record", async () => {
      renderTrust(
        withSlack({
          channels: [
            { id: "C001", name: "general", botIsMember: true, selected: true },
            { id: "C002", name: "engineering", botIsMember: true, selected: true },
          ],
          notice: NOTICE,
        }),
      );

      expect(
        await screen.findByText(/cairn is reading 2 channels: #general, #engineering\./i),
      ).toBeVisible();
    });

    it("names only the channels the backend said were chosen", async () => {
      // **The commitment this page turns on.** Its whole claim is that its
      // numbers are read from the workspace. A channel CAIRN could read but
      // nobody selected is not a channel CAIRN is reading, and listing it here
      // would overstate the surveillance on the page that exists to be checked.
      renderTrust(
        withSlack({
          channels: [
            { id: "C001", name: "general", botIsMember: true, selected: true },
            { id: "C002", name: "engineering", botIsMember: true, selected: false },
          ],
          notice: NOTICE,
        }),
      );

      expect(await screen.findByText(/cairn is reading 1 channel: #general\./i)).toBeVisible();
    });

    it("keeps the record read-only and says where it is changed", async () => {
      renderTrust(
        withSlack({
          channels: [{ id: "C001", name: "general", botIsMember: true, selected: true }],
          notice: NOTICE,
        }),
      );

      await screen.findByText(/cairn is reading 1 channel/i);
      expect(screen.queryByRole("button", { name: /choose channels/i })).not.toBeInTheDocument();
      expect(
        screen.getByText(/an owner or an admin chooses these in workspace settings/i),
      ).toBeVisible();
    });

    it("says the record is incomplete rather than failing the whole page", async () => {
      // One detail inside a record on a page full of records. An alert about a
      // channel list is out of proportion to what a reader came here for.
      renderTrust({
        ...withSlack({ channels: [], notice: NOTICE }),
        listSlackChannels: vi.fn(() => Promise.reject(apiError(503))),
      });

      await screen.findByRole("heading", { name: /slack — northwind hq/i });
      expect(
        await screen.findByText(/could not read which slack channels are selected/i),
      ).toBeVisible();
      expect(screen.getByText(/90 days, then deleted/i)).toBeVisible();
    });

    it("names the scopes and the invite rule here too", async () => {
      // The same three facts, from the same constants, so the workspace screen
      // and the trust record cannot come to disagree about what CAIRN asks for.
      renderTrust();

      await screen.findByRole("heading", { name: /^slack$/i });
      const slack = within(card(/^slack$/i));

      expect(slack.getByText("channels:history")).toBeVisible();
      expect(slack.getByText(/\/invite @CAIRN/i)).toBeVisible();
      expect(slack.getByText(/no permission to write anything to slack/i)).toBeVisible();
    });
  });

  it("does not let the record imply Google Chat is available", async () => {
    // The record has to explain why the answer is "not connected", and here the
    // reason is not that nobody got round to it: the restricted scope is
    // unverified, so no authorisation can complete. A trust page that lists a
    // source as merely unconnected, on a screen whose whole claim is that its
    // statements can be checked, is the wrong sentence in the worst place.
    renderTrust();

    await screen.findByRole("heading", { name: /^google chat$/i });
    const chat = within(card(/^google chat$/i));

    expect(chat.getByText(/cannot be connected yet/i)).toBeVisible();
    expect(chat.getByText(/casa security assessment/i)).toBeVisible();
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

      expect(await screen.findByText(/sam@cairn.dev on /i)).toBeVisible();
      expect(screen.getByText(/investigating an integration failure/i)).toBeVisible();
      expect(screen.getByText(/ali@acme.example.com/)).toBeVisible();
    });

    it("states the duration that was asked for", async () => {
      // The approver is agreeing to a length of access. Approving a duration
      // nobody displayed is consent to an unstated term.
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      expect(await screen.findByText(/for up to 40 minutes/i)).toBeVisible();
    });

    it("says which scope each recorded access was performed under", async () => {
      // "They opened something" and "they opened your team's work" are
      // different answers, and the event carries which one it was.
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      expect(
        await screen.findByText(
          /read 3 recorded activity statements \(settings and diagnostics\)/i,
        ),
      ).toBeVisible();
    });

    it("says plainly when approved access was never used", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([{ ...SUPPORT_SESSION, events: [] }])),
      });

      expect(await screen.findByText(/access was granted and never used/i)).toBeVisible();
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

    it("explains the effect before ending access, and only then ends it", async () => {
      // Ending access is not destructive to data, but the other party notices
      // immediately, so the effect is stated before the act.
      const revokeSupportSession = vi.fn(() => Promise.resolve(SUPPORT_SESSION));
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([{ ...SUPPORT_SESSION, active: true }])),
        revokeSupportSession,
      });

      await userEvent.click(await screen.findByRole("button", { name: /end access now/i }));
      expect(revokeSupportSession).not.toHaveBeenCalled();
      expect(screen.getByText(/lose access to this workspace immediately/i)).toBeVisible();

      await userEvent.click(screen.getByRole("button", { name: /^end access now$/i }));

      expect(revokeSupportSession).toHaveBeenCalledWith(WORKSPACE, SUPPORT_SESSION.id);
    });

    it("lets the reader back out of ending access", async () => {
      const revokeSupportSession = vi.fn(() => Promise.resolve(SUPPORT_SESSION));
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([{ ...SUPPORT_SESSION, active: true }])),
        revokeSupportSession,
      });

      await userEvent.click(await screen.findByRole("button", { name: /end access now/i }));
      await userEvent.click(screen.getByRole("button", { name: /leave it open/i }));

      expect(revokeSupportSession).not.toHaveBeenCalled();
      expect(
        screen.queryByText(/lose access to this workspace immediately/i),
      ).not.toBeInTheDocument();
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

        expect(await screen.findByText(/sam@cairn.dev on /i)).toBeVisible();
        expect(screen.queryByRole("button", { name: /allow/i })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /refuse/i })).not.toBeInTheDocument();
      },
    );

    it.each(["member", "viewer"] as const)(
      "tells a %s who can decide, rather than showing them nothing",
      async (role) => {
        // Absence is ambiguous: it leaves the reader unable to tell whether a
        // pending request is unattended or simply not theirs to act on. A
        // Viewer has the same stake in this record as an Owner.
        renderTrust(
          {
            listSupportSessions: vi.fn(() =>
              Promise.resolve([{ ...SUPPORT_SESSION, status: "pending" as const, active: false }]),
            ),
          },
          role,
        );

        expect(
          await screen.findByText(/an owner or an admin of this workspace decides this request/i),
        ).toBeVisible();
      },
    );

    it("names who ended a session, not who approved it", async () => {
      // The two are different acts by possibly different people. Rendering only
      // the approver beside "ended early" attributed the ending to them.
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([
            {
              ...SUPPORT_SESSION,
              status: "revoked" as const,
              active: false,
              revokedAt: "2026-08-12T09:20:00Z",
              revokedBy: "dana@acme.example.com",
            },
          ]),
        ),
      });

      expect(await screen.findByText(/^ended early$/i)).toBeVisible();
      expect(screen.getByText(/dana@acme.example.com/)).toBeVisible();
      expect(screen.queryByText(/ended by you/i)).not.toBeInTheDocument();
    });

    it("says the revoker is unknown rather than borrowing the approver's name", async () => {
      // Sessions ended before CAIRN recorded the revoker cannot name one, and
      // the honest answer is to say so.
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([
            {
              ...SUPPORT_SESSION,
              status: "revoked" as const,
              active: false,
              revokedAt: "2026-08-12T09:20:00Z",
              revokedBy: null,
            },
          ]),
        ),
      });

      expect(await screen.findByText(/who ended it was not recorded/i)).toBeVisible();
    });

    it("states the approved scope, expiry and break-glass state", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      expect(await screen.findByText(/for settings and diagnostics/i)).toBeVisible();
      // Break-glass is answered explicitly. Silence would leave a customer
      // reading a privacy record unable to tell whether the question was asked
      // and answered "no", or never asked at all.
      expect(screen.getByText(/^no$/i)).toBeVisible();
    });

    it("does not describe a finished session in the present tense", async () => {
      // The row's status already says the access ended; "Ends {past date}" on
      // the same row contradicts it.
      renderTrust({
        listSupportSessions: vi.fn(() => Promise.resolve([SUPPORT_SESSION])),
      });

      await screen.findByText(/sam@cairn.dev on /i);
      expect(screen.queryByText(/^expires$/i)).not.toBeInTheDocument();
      expect(screen.getByText(/^expired$/i)).toBeVisible();
    });

    it("uses a future tense for a session that has not run out yet", async () => {
      renderTrust({
        listSupportSessions: vi.fn(() =>
          Promise.resolve([
            { ...SUPPORT_SESSION, active: true, expiresAt: "2099-01-01T00:00:00Z" },
          ]),
        ),
      });

      expect(await screen.findByText(/^expires$/i)).toBeVisible();
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

/**
 * Google Chat, wired into the same screen.
 *
 * Step 33 is deliberately not a third integration system: the card, the connect
 * button, the three OAuth outcomes and the confirmation are the ones Slack
 * already uses. What this block is for is the handful of things that are
 * genuinely different about Google, and each of them is a way this screen could
 * tell somebody a false thing about surveillance.
 *
 * - **A tick comes only from a backend-confirmed `selected`.** `PUT` answers
 *   with resource names, `reconcileSpaces` folds them back, and a refused save
 *   leaves the checkbox exactly where it was.
 * - **Selected is not delivering.** Google's subscriptions expire and their
 *   automatic renewal fails when the authorising account loses access. A space
 *   drawn as fine while its subscription is suspended is the failure the whole
 *   picker exists to prevent.
 * - **A personal Gmail account cannot authorise this**, which is the sentence
 *   that decides whether pressing Connect can work at all.
 */
describe("connecting Google Chat", () => {
  const GOOGLE_CHAT: Integration = {
    source: "google_chat",
    account: "northwind.example",
    installationId: 11,
    connectedAt: "2026-07-20T09:00:00Z",
    disconnectedAt: null,
    suspended: false,
  };

  /** The server's own standing sentence, sent with every space response. */
  const SPACE_NOTICE =
    "CAIRN reads a space only from the moment you select it, and only while its Google subscription is active.";

  const SPACES: GoogleChatSpaceList = {
    spaces: [
      {
        name: "spaces/AAAA1",
        displayName: "Platform",
        eligible: true,
        selected: true,
        subscriptionState: "active",
        expireTime: "2026-09-01T09:00:00Z",
        errorCategory: null,
      },
      {
        name: "spaces/AAAA2",
        displayName: "Design",
        eligible: true,
        selected: false,
        subscriptionState: null,
        expireTime: null,
        errorCategory: null,
      },
      {
        name: "spaces/AAAA3",
        displayName: "Ali and Jo",
        eligible: false,
        selected: false,
        subscriptionState: null,
        expireTime: null,
        errorCategory: "configuration_invalid",
      },
    ],
    notice: SPACE_NOTICE,
  };

  const GOOGLE_INSTALL: GoogleChatInstall = {
    authorizeUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=nonce",
    expiresAt: "2026-08-17T10:15:00Z",
    notice: "This link authorises one Google Workspace account.",
  };

  const GOOGLE_DISCONNECTED: GoogleChatDisconnect = {
    state: "disconnected",
    disconnectedAt: "2026-08-17T10:20:00Z",
    credentialCleared: true,
    retentionNotice: "What was already recorded stays until the retention period ends.",
  };

  function saved(spaceNames: string[]): GoogleChatSpaceSelection {
    return { spaceNames, notice: SPACE_NOTICE };
  }

  /** A workspace with Google Chat connected, and every endpoint stubbed. */
  function googleClient(overrides = {}): ReturnType<typeof createStubClient> {
    return client({
      listIntegrations: vi.fn(() => Promise.resolve([GOOGLE_CHAT])),
      startGoogleChatInstall: vi.fn(() => Promise.resolve(GOOGLE_INSTALL)),
      listGoogleChatSpaces: vi.fn(() => Promise.resolve(SPACES)),
      setGoogleChatSpaces: vi.fn(() => Promise.resolve(saved(["spaces/AAAA1"]))),
      disconnectGoogleChat: vi.fn(() => Promise.resolve(GOOGLE_DISCONNECTED)),
      ...overrides,
    });
  }

  /** Google Chat not yet connected — the card is listed all the same. */
  function unconnectedGoogleClient(overrides = {}): ReturnType<typeof createStubClient> {
    return googleClient({
      listIntegrations: vi.fn(() => Promise.resolve(INTEGRATIONS)),
      ...overrides,
    });
  }

  /** See `captureNavigation` above: jsdom neither performs nor records it. */
  function captureGoogleNavigation(): ReturnType<typeof vi.fn> {
    const assign = vi.fn();
    const { href, origin, pathname, search } = window.location;
    vi.stubGlobal("location", { href, origin, pathname, search, assign });
    return assign;
  }

  async function openSpaces(): Promise<void> {
    await userEvent.click(await screen.findByRole("button", { name: /choose spaces/i }));
  }

  describe("what the reader is told before they authorise anything", () => {
    it("lists Google Chat even though nobody has connected it", async () => {
      // The scopes, the refusals and the account requirement have to be readable
      // while the answer is still "no".
      renderAdmin(unconnectedGoogleClient());

      await screen.findByRole("heading", { name: /^google chat$/i });
      expect(
        within(card(/^google chat$/i)).getByText(/reading nothing from google chat/i),
      ).toBeVisible();
    });

    it("names both scopes exactly, in the literal form and in plain words", async () => {
      renderAdmin(unconnectedGoogleClient());

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.getByText("chat.spaces.readonly")).toBeVisible();
      expect(chat.getByText("chat.messages.readonly")).toBeVisible();
      expect(
        chat.getByText(/list the spaces the person who authorises cairn can see/i),
      ).toBeVisible();
      expect(chat.getByText(/read the messages in the spaces you select/i)).toBeVisible();
    });

    it("asks for no third scope", async () => {
      // Locked deliberately. The day somebody adds a scope this fails, and
      // whoever added it has to write the sentence that explains it to a
      // customer.
      renderAdmin(unconnectedGoogleClient());

      await screen.findByRole("heading", { name: /^google chat$/i });
      const scopes = within(card(/^google chat$/i)).getAllByText(/^chat\./);

      expect(scopes.map((node) => node.textContent)).toEqual([
        "chat.spaces.readonly",
        "chat.messages.readonly",
      ]);
    });

    it("states the six things the grant makes impossible", async () => {
      renderAdmin(unconnectedGoogleClient());

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.getByText(/asks for no permission to write to google chat/i)).toBeVisible();
      expect(chat.getByText(/read your direct messages/i)).toBeVisible();
      expect(chat.getByText(/react to a message/i)).toBeVisible();
      expect(chat.getByText(/no read-state, no presence and no typing indicator/i)).toBeVisible();
      expect(chat.getByText(/does not request membership data/i)).toBeVisible();
      expect(chat.getByText(/no admin scope and no organisation-wide access/i)).toBeVisible();
    });

    it("says that a personal Gmail account cannot authorise it", async () => {
      // **The sentence that decides whether Connect can work.** Without it,
      // somebody meets an opaque Google error and cannot tell a wrong account
      // from a broken product.
      renderAdmin(unconnectedGoogleClient());

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.getByText(/a personal gmail account cannot authorise this/i)).toBeVisible();
      expect(chat.getByText(/belong to a google workspace organisation/i)).toBeVisible();
    });

    it("says plainly that Google Chat cannot be connected yet, and why", async () => {
      // **Google Chat is not live.** `chat.messages.readonly` is a RESTRICTED
      // scope: it needs Google's OAuth verification and an independent CASA
      // assessment, and until both are finished no authorisation can succeed
      // (docs/runbooks/connectors.md). The Connect button is real, so without
      // this sentence the only possible outcome is an opaque Google error the
      // reader cannot tell from a broken product or a wrong account.
      //
      // The scope name and the assessment are the checkable half. "Coming soon"
      // would be the same claim with the evidence removed.
      renderAdmin(unconnectedGoogleClient());

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.getByText(/cannot be connected yet/i)).toBeVisible();
      expect(chat.getByText(/google classes as restricted/i)).toBeVisible();
      expect(chat.getByText(/casa security assessment/i)).toBeVisible();
    });
  });

  describe("starting the grant", () => {
    it("asks the API where to send the customer, then sends them", async () => {
      // Two steps rather than a link: the URL does not exist until it is asked
      // for, because the install endpoint mints a single-use state nonce.
      const assign = captureGoogleNavigation();
      const startGoogleChatInstall = vi.fn(() => Promise.resolve(GOOGLE_INSTALL));
      renderAdmin(unconnectedGoogleClient({ startGoogleChatInstall }));

      await userEvent.click(await screen.findByRole("button", { name: /connect google chat/i }));

      expect(startGoogleChatInstall).toHaveBeenCalledWith(WORKSPACE);
      expect(assign).toHaveBeenCalledWith(GOOGLE_INSTALL.authorizeUrl);
    });

    it("says when the link it just minted stops working", async () => {
      // A state nonce is single-use and time-boxed. Somebody who opens the
      // consent screen and comes back after lunch gets a failure whose only
      // explanation is this line.
      captureGoogleNavigation();
      renderAdmin(unconnectedGoogleClient());

      await userEvent.click(await screen.findByRole("button", { name: /connect google chat/i }));

      expect(await screen.findByText(/this link stops working at/i)).toBeVisible();
      expect(screen.getByText(/authorises one google workspace account/i)).toBeVisible();
    });

    it("says which source failed to start, next to that card", async () => {
      renderAdmin(
        unconnectedGoogleClient({
          startGoogleChatInstall: vi.fn(() => Promise.reject(apiError(500))),
        }),
      );

      await userEvent.click(await screen.findByRole("button", { name: /connect google chat/i }));

      const chat = within(card(/^google chat$/i));
      expect(await chat.findByRole("alert")).toBeVisible();
    });

    it("offers Reconnect once the connection has stopped working", async () => {
      renderAdmin(
        googleClient({
          listIntegrations: vi.fn(() => Promise.resolve([{ ...GOOGLE_CHAT, suspended: true }])),
        }),
      );

      expect(await screen.findByRole("button", { name: /reconnect google chat/i })).toBeVisible();
    });
  });

  describe("coming back from Google's consent screen", () => {
    it("says plainly that it worked, and that nothing is being read yet", async () => {
      renderAdmin(googleClient(), "googleChat=connected");

      expect(await screen.findByText(/google chat is connected/i)).toBeVisible();
      expect(screen.getByText(/no spaces are chosen yet, so nothing is being read/i)).toBeVisible();
    });

    it("treats a denial as an answer, not as a failure", async () => {
      // Somebody was asked for permission and said no. An alert and an apology
      // would teach them their deliberate decision broke the product.
      renderAdmin(unconnectedGoogleClient(), "googleChat=denied");

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.getByText(/nothing was connected/i)).toBeVisible();
      expect(chat.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("says a failure connected nothing, and puts it where the reader is looking", async () => {
      renderAdmin(unconnectedGoogleClient(), "googleChat=error");

      await screen.findByRole("heading", { name: /^google chat$/i });

      expect(within(card(/^google chat$/i)).getByRole("alert")).toHaveTextContent(
        /nothing was connected and nothing is being read/i,
      );
    });

    it("puts a Google return on the Google card and not on Slack's", async () => {
      // One parameter per provider. A shared one would put a Google denial on
      // the Slack card, which is a false statement about which grant was
      // refused.
      renderAdmin(unconnectedGoogleClient(), "googleChat=denied");

      await screen.findByRole("heading", { name: /^google chat$/i });

      expect(within(card(/^google chat$/i)).getByText(/nothing was connected/i)).toBeVisible();
      expect(within(card(/^slack$/i)).queryByText(/nothing was connected/i)).toBeNull();
    });

    it("ignores a return value it does not recognise", async () => {
      // The value is attacker-controllable. Rendering an arbitrary one would put
      // a stranger's word on a page whose whole point is that its words are
      // CAIRN's.
      renderAdmin(unconnectedGoogleClient(), "googleChat=%3Cscript%3E");

      await screen.findByRole("heading", { name: /^google chat$/i });

      expect(within(card(/^google chat$/i)).queryByText(/nothing was connected/i)).toBeNull();
    });
  });

  describe("choosing spaces", () => {
    it("sends the whole selection, never a delta", async () => {
      // PUT replaces rather than merges, so an unchecked box has to arrive as an
      // absence — and an absence is only meaningful when everything else is
      // present.
      const setGoogleChatSpaces = vi.fn(() =>
        Promise.resolve(saved(["spaces/AAAA1", "spaces/AAAA2"])),
      );
      renderAdmin(googleClient({ setGoogleChatSpaces }));
      await openSpaces();

      await userEvent.click(screen.getByRole("checkbox", { name: "Design" }));

      expect(setGoogleChatSpaces).toHaveBeenCalledWith(WORKSPACE, ["spaces/AAAA1", "spaces/AAAA2"]);
    });

    it("ticks only what the save came back with", async () => {
      // **The rule.** The server answered with one name, so one box is ticked —
      // whatever was clicked.
      renderAdmin(
        googleClient({
          setGoogleChatSpaces: vi.fn(() => Promise.resolve(saved(["spaces/AAAA2"]))),
        }),
      );
      await openSpaces();

      await userEvent.click(screen.getByRole("checkbox", { name: "Design" }));

      expect(await screen.findByRole("checkbox", { name: "Design" })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: "Platform" })).not.toBeChecked();
    });

    it("leaves the box where it was when the save is refused, and says why", async () => {
      renderAdmin(
        googleClient({ setGoogleChatSpaces: vi.fn(() => Promise.reject(apiError(403))) }),
      );
      await openSpaces();

      await userEvent.click(screen.getByRole("checkbox", { name: "Design" }));

      expect(await screen.findByText(/does not have access to that/i)).toBeVisible();
      expect(screen.getByRole("checkbox", { name: "Design" })).not.toBeChecked();
    });

    it("shows an ineligible space as unselectable, with a reason, rather than hiding it", async () => {
      renderAdmin(googleClient());
      await openSpaces();

      const dm = screen.getByRole("checkbox", { name: "Ali and Jo" });
      expect(dm).toBeDisabled();
      expect(
        screen.getByText(/cairn cannot read this space, so it cannot be chosen/i),
      ).toBeVisible();
    });

    it("says a selected space is not delivering when its subscription is suspended", async () => {
      renderAdmin(
        googleClient({
          listGoogleChatSpaces: vi.fn(() =>
            Promise.resolve({
              ...SPACES,
              spaces: [{ ...SPACES.spaces![0]!, subscriptionState: "suspended" }],
            }),
          ),
        }),
      );
      await openSpaces();

      expect(
        screen.getByText(/the subscription is suspended, so nothing is arriving from this space/i),
      ).toBeVisible();
    });

    it("warns while a subscription is renewing rather than after it has failed", async () => {
      renderAdmin(
        googleClient({
          listGoogleChatSpaces: vi.fn(() =>
            Promise.resolve({
              ...SPACES,
              spaces: [{ ...SPACES.spaces![0]!, subscriptionState: "renewing" }],
            }),
          ),
        }),
      );
      await openSpaces();

      expect(screen.getByText(/the subscription is renewing/i)).toBeVisible();
      expect(screen.getByText(/the space stops delivering/i)).toBeVisible();
    });

    it("shows a skeleton while the spaces load, and announces it", async () => {
      const pending = new Promise<GoogleChatSpaceList>(() => undefined);
      renderAdmin(googleClient({ listGoogleChatSpaces: vi.fn(() => pending) }));

      expect(await screen.findByText(/loading the google chat spaces/i)).toBeInTheDocument();
    });

    it("answers a permission refusal rather than reporting a generic failure", async () => {
      renderAdmin(
        googleClient({ listGoogleChatSpaces: vi.fn(() => Promise.reject(apiError(403))) }),
      );

      expect(await screen.findByText(/does not have access to that/i)).toBeVisible();
    });

    it("offers a retry when the spaces could not be loaded", async () => {
      const listGoogleChatSpaces = vi
        .fn()
        .mockRejectedValueOnce(apiError(500))
        .mockResolvedValue(SPACES);
      renderAdmin(googleClient({ listGoogleChatSpaces }));

      await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

      expect(await screen.findByRole("button", { name: /choose spaces/i })).toBeVisible();
      expect(listGoogleChatSpaces).toHaveBeenCalledTimes(2);
    });

    it("gives a Member the record read-only, and says who can change it", async () => {
      const member = googleClient({
        getSession: vi.fn(() =>
          Promise.resolve({
            ...SESSION,
            workspaces: [{ ...SESSION.workspaces[0]!, role: "member" as const }],
          }),
        ),
      });
      renderAdmin(member);

      await screen.findByRole("heading", { name: /spaces cairn reads/i });

      expect(screen.queryByRole("button", { name: /choose spaces/i })).not.toBeInTheDocument();
      expect(
        screen.getByText(
          /an owner or an admin of this workspace chooses which google chat spaces/i,
        ),
      ).toBeVisible();
      // The record itself, not only a count.
      expect(screen.getByText("Platform")).toBeVisible();
    });

    it("gives a Viewer no connect control, and names who has one", async () => {
      const viewer = unconnectedGoogleClient({
        getSession: vi.fn(() =>
          Promise.resolve({
            ...SESSION,
            workspaces: [{ ...SESSION.workspaces[0]!, role: "viewer" as const }],
          }),
        ),
      });
      renderAdmin(viewer);

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.queryByRole("button", { name: /connect google chat/i })).not.toBeInTheDocument();
      expect(
        chat.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
      ).toBeVisible();
      // And they can still read exactly what it would ask for.
      expect(chat.getByText("chat.messages.readonly")).toBeVisible();
    });

    it("restores focus to the trigger when the picker is closed", async () => {
      renderAdmin(googleClient());
      await openSpaces();

      await userEvent.click(screen.getByRole("button", { name: /done choosing spaces/i }));

      expect(screen.getByRole("button", { name: /choose spaces/i })).toHaveFocus();
    });

    it("passes an axe audit with the space picker open", async () => {
      const { container } = renderAdmin(googleClient());
      await openSpaces();

      await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
    });
  });

  describe("disconnecting", () => {
    it("states the truth before it happens", async () => {
      renderAdmin(googleClient());

      await screen.findByRole("heading", { name: /^google chat — northwind.example$/i });
      const chat = within(card(/^google chat — northwind.example$/i));
      await userEvent.click(chat.getByRole("button", { name: /^disconnect$/i }));

      const confirmation = screen.getByRole("group", { name: /disconnect google chat/i });
      expect(confirmation).toHaveTextContent(/stops new collection immediately/i);
      expect(confirmation).toHaveTextContent(/deletes the google credential cairn stored/i);
      expect(confirmation).toHaveTextContent(/does not delete what has already been recorded/i);
    });

    it("disconnects only after the reader has confirmed", async () => {
      const disconnectGoogleChat = vi.fn(() => Promise.resolve(GOOGLE_DISCONNECTED));
      renderAdmin(googleClient({ disconnectGoogleChat }));

      await screen.findByRole("heading", { name: /^google chat/i });
      const chat = within(card(/^google chat/i));
      await userEvent.click(chat.getByRole("button", { name: /^disconnect$/i }));
      expect(disconnectGoogleChat).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole("button", { name: /disconnect google chat/i }));

      expect(disconnectGoogleChat).toHaveBeenCalledWith(WORKSPACE);
    });

    it("says which card failed when the disconnect is refused", async () => {
      renderAdmin(
        googleClient({ disconnectGoogleChat: vi.fn(() => Promise.reject(apiError(403))) }),
      );

      await screen.findByRole("heading", { name: /^google chat/i });
      const chat = within(card(/^google chat/i));
      await userEvent.click(chat.getByRole("button", { name: /^disconnect$/i }));
      await userEvent.click(screen.getByRole("button", { name: /disconnect google chat/i }));

      expect(await chat.findByRole("alert")).toHaveTextContent(/does not have access to that/i);
    });
  });

  describe("the Trust page's record of it", () => {
    function renderTrustWith(stub: ReturnType<typeof createStubClient>): void {
      renderRoute(
        <AppLayout>
          <TrustPage />
        </AppLayout>,
        { client: stub, route: "/trust" },
      );
    }

    /** Enough of the Trust payload for the page to render around the record. */
    const GOOGLE_TRUST: Trust = {
      sources: [
        {
          source: "google_chat",
          label: "Google Chat",
          reads: "Messages in the spaces you choose. Never direct messages.",
          connected: true,
        },
      ],
      refusals: ["CAIRN never scores or ranks people."],
      commitments: [
        { title: "Everyone sees the same thing", detail: "Roles decide what you can configure." },
      ],
      retentionDays: 90,
      region: "us-central1",
      awaitingNotification: 0,
      subprocessors: [{ title: "Google Cloud (Vertex AI)", detail: "Runs the models." }],
    };

    /** The Trust page needs its own payload as well as the connections. */
    function trustClient(overrides = {}): ReturnType<typeof createStubClient> {
      return googleClient({ getTrust: vi.fn(() => Promise.resolve(GOOGLE_TRUST)), ...overrides });
    }

    it("records the spaces and their subscription state, read-only", async () => {
      renderTrustWith(trustClient());

      await screen.findByRole("heading", { name: /spaces cairn reads/i });

      expect(screen.getByText("Platform")).toBeVisible();
      expect(
        screen.getByText(
          /the subscription is active, so messages from this space are reaching cairn/i,
        ),
      ).toBeVisible();
      expect(screen.queryByRole("button", { name: /choose spaces/i })).not.toBeInTheDocument();
    });

    it("invents no last delivery when the connection recorded none", async () => {
      // **The page's whole claim is that its numbers are read from the
      // workspace.** A plausible "Last successful sync 4 minutes ago" from a
      // field the server never sent would discredit every other line on it.
      renderTrustWith(trustClient());

      await screen.findByRole("heading", { name: /^google chat — northwind.example$/i });

      expect(
        within(card(/^google chat — northwind.example$/i)).queryByText(/last successful sync/i),
      ).toBeNull();
    });

    it("says the record is incomplete rather than empty when the spaces cannot be read", async () => {
      // One detail inside a record on a page full of records. An error panel
      // about a space list is out of proportion to what a reader came for.
      renderTrustWith(
        trustClient({ listGoogleChatSpaces: vi.fn(() => Promise.reject(apiError(500))) }),
      );

      expect(
        await screen.findByText(/could not read which google chat spaces are selected just now/i),
      ).toBeVisible();
    });
  });
});

/**
 * Attribution health: the aggregate, and the list that must never appear
 * beside it.
 *
 * This is the screen where "which people are unresolved?" first seems
 * reasonable — it is a real question an Owner has, and every other admin area
 * would answer it. md/05 §B.3.3 makes a per-person attribution breakdown a
 * product-reclassifying feature, and md/15 §2.3 forbids an administrator seeing
 * more about a member than the member sees about themselves. So the assertions
 * here are as much about absence as about counts, because the failure is
 * additive: nobody deletes the counts, somebody adds names next to them.
 */
describe("attribution health", () => {
  it("states the counts by source", async () => {
    renderAdmin();

    // Awaited on the counts rather than on the heading: the section paints its
    // own title before the read resolves, so a query made at the heading is a
    // query made against the skeleton.
    const list = await screen.findByRole("list", { name: /accounts by source/i });
    expect(within(list).getByText(/7 claimed · 2 unclaimed/)).toBeVisible();
    expect(within(list).getByText(/4 claimed · 0 unclaimed/)).toBeVisible();
    expect(within(list).getByText(/0 claimed · 5 unclaimed/)).toBeVisible();
  });

  it("carries no per-person data of any kind", async () => {
    renderAdmin();
    await screen.findByRole("list", { name: /accounts by source/i });
    const heading = screen.getByRole("heading", { name: /attribution health/i });
    const section = heading.closest("section");
    if (section === null) throw new Error("Attribution health is not inside a section");

    // Both members of the fixture workspace, by name and by address. Neither is
    // in the response; this asserts nothing on the client puts them back.
    for (const member of MEMBERS) {
      expect(section.textContent).not.toContain(member.email);
      if (member.displayName != null) {
        expect(section.textContent).not.toContain(member.displayName);
      }
    }
    // And no control that would reassign somebody's account, which is the other
    // half of the same rule: a member's record is theirs to correct.
    expect(within(section).queryByRole("button", { name: /reassign/i })).toBeNull();
    expect(within(section).queryByRole("combobox")).toBeNull();
  });

  it("says what it cannot answer, in the server's own words", async () => {
    renderAdmin();

    expect(await screen.findByText(HEALTH.notice)).toBeVisible();
    expect(screen.getByText(/ask the team to confirm their own accounts/i)).toBeVisible();
  });

  it("reports a failure without breaking the rest of the screen", async () => {
    renderAdmin(client({ getAttributionHealth: vi.fn(() => Promise.reject(apiError(500))) }));

    expect(await screen.findByText(/attribution health could not be loaded/i)).toBeVisible();
    expect(screen.getByRole("list", { name: /members/i })).toBeVisible();
  });

  it("has no axe violations", async () => {
    const { container } = renderAdmin();
    await screen.findByRole("list", { name: /accounts by source/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

/**
 * Google Meet, wired into the same screen.
 *
 * Step 36A adds no new integration system: the card, the connect control, the
 * three OAuth outcomes and the confirmation are the ones Slack and Chat already
 * use. What is genuinely different about Meet is what the reader believes before
 * they arrive.
 *
 * - **CAIRN does not join calls or start recordings.** Everybody who hears
 *   "CAIRN does meetings" pictures a bot in the corner of the call. Agreement
 *   obtained without correcting that is agreement to something the person
 *   thought was happening anyway.
 * - **There is no picker, and there must never be one.** A meeting is not chosen
 *   by an administrator; every person expected in it answers for themselves,
 *   from their own session (md/03 §3.1). A space-picker-shaped control here
 *   would be an employer's answer standing in for an employee's.
 * - **The status word comes from the API or is not shown.** "Eligible" and
 *   "subscribed" are different facts, and an absent field is not "fine".
 * - **Meet is not live**, and its blocker is not Chat's: `meetings.space.
 *   readonly` is sensitive rather than restricted, so it needs Google's OAuth
 *   verification and not a CASA assessment. Copying Chat's sentence would
 *   overstate it on the one screen that cannot be wrong about a scope.
 */
describe("connecting Google Meet", () => {
  const GOOGLE_MEET: Integration = {
    source: "google_meet",
    account: "northwind.example",
    installationId: 12,
    connectedAt: "2026-07-20T09:00:00Z",
    disconnectedAt: null,
    suspended: false,
  };

  const MEET_INSTALL: GoogleMeetInstall = {
    authorizeUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=meet-nonce",
    expiresAt: "2026-08-17T10:15:00Z",
    // The server's own sentence, which the card renders rather than paraphrases.
    notice:
      "Connecting Google Meet does not let CAIRN collect anything on its own. " +
      "CAIRN watches a meeting only after every person invited to it has agreed.",
  };

  const MEET_DISCONNECTED: GoogleMeetDisconnect = {
    state: "disconnected",
    disconnectedAt: "2026-08-17T10:20:00Z",
    subscriptionsRemoved: 2,
    credentialCleared: true,
    retentionNotice: "What CAIRN already recorded is not deleted by disconnecting.",
  };

  /** A payload carrying a subscription state — a field `Integration` does not
   * publish yet, which the card reads defensively for exactly that reason. */
  function withState(subscriptionState: string): Integration {
    return { ...GOOGLE_MEET, subscriptionState } as Integration;
  }

  /** A workspace with Google Meet connected, and both endpoints stubbed. */
  function meetClient(overrides = {}): ReturnType<typeof createStubClient> {
    return client({
      listIntegrations: vi.fn(() => Promise.resolve([GOOGLE_MEET])),
      startGoogleMeetInstall: vi.fn(() => Promise.resolve(MEET_INSTALL)),
      disconnectGoogleMeet: vi.fn(() => Promise.resolve(MEET_DISCONNECTED)),
      ...overrides,
    });
  }

  /** Google Meet not yet connected — the card is listed all the same. */
  function unconnectedMeetClient(overrides = {}): ReturnType<typeof createStubClient> {
    return meetClient({
      listIntegrations: vi.fn(() => Promise.resolve(INTEGRATIONS)),
      ...overrides,
    });
  }

  /** See `captureNavigation` above: jsdom neither performs nor records it. */
  function captureMeetNavigation(): ReturnType<typeof vi.fn> {
    const assign = vi.fn();
    const { href, origin, pathname, search } = window.location;
    vi.stubGlobal("location", { href, origin, pathname, search, assign });
    return assign;
  }

  describe("what the reader is told before they authorise anything", () => {
    it("lists Google Meet even though nobody has connected it", async () => {
      renderAdmin(unconnectedMeetClient());

      await screen.findByRole("heading", { name: /^google meet$/i });
      expect(
        within(card(/^google meet$/i)).getByText(/receiving nothing from google meet/i),
      ).toBeVisible();
    });

    it("says CAIRN does not join calls or start recordings", async () => {
      // **The sentence the whole connector sits behind**, on the screen where
      // somebody is about to press Connect.
      renderAdmin(unconnectedMeetClient());

      await screen.findByRole("heading", { name: /^google meet$/i });

      expect(
        within(card(/^google meet$/i)).getByText(
          /CAIRN does not join calls or start recordings\. It can only receive a transcript the meeting platform itself created, and only after every participant in that meeting has agreed\./,
        ),
      ).toBeVisible();
    });

    it("names the scope exactly, and what it does and does not permit", async () => {
      renderAdmin(unconnectedMeetClient());

      await screen.findByRole("heading", { name: /^google meet$/i });
      const meet = within(card(/^google meet$/i));

      expect(meet.getByText("meetings.space.readonly")).toBeVisible();
      expect(meet.getByText(/lets Google tell CAIRN that a transcript exists/i)).toBeVisible();
      expect(meet.getAllByText(/^meetings\./)).toHaveLength(1);
    });

    it("says a transcript needs a further permission CAIRN does not hold", async () => {
      renderAdmin(unconnectedMeetClient());

      await screen.findByRole("heading", { name: /^google meet$/i });

      expect(
        within(card(/^google meet$/i)).getByText(/a further, separate permission/i),
      ).toBeVisible();
    });

    it("says plainly that Google Meet cannot be connected yet, and why", async () => {
      // **Meet is not live.** The Connect button is real, so without this
      // sentence its only possible outcome is an opaque Google error the reader
      // cannot tell from a broken product.
      //
      // And the blocker named is Meet's own. `meetings.space.readonly` is
      // SENSITIVE, so it needs Google's OAuth verification — not the CASA
      // assessment Chat's RESTRICTED scope needs. Overstating it would be just
      // as wrong as understating it, on a screen whose claim is checkability.
      renderAdmin(unconnectedMeetClient());

      await screen.findByRole("heading", { name: /^google meet$/i });
      const meet = within(card(/^google meet$/i));

      expect(meet.getByText(/cannot be connected yet/i)).toBeVisible();
      expect(meet.getByText(/OAuth app verification/i)).toBeVisible();
      expect(meet.queryByText(/\blive\b/i)).toBeNull();
    });

    it("renders no meeting reference, joining code, title or attendee anywhere on the card", async () => {
      // A joining code is a credential — Step 35 removed it from every response
      // for that reason — and an attendee list is the analytic md/03 §5.4
      // forbids. Asserted against the markup, because the way one arrives is
      // somebody threading a field through later.
      renderAdmin(meetClient());

      await screen.findByRole("heading", { name: /^google meet/i });
      const html = card(/^google meet/i).innerHTML;

      expect(html).not.toMatch(/meet\.google\.com/i);
      expect(html).not.toMatch(/\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b/);
      expect(html).not.toMatch(/spaces\/[A-Za-z0-9_-]+|conferenceRecords|meetingCode|meetingUri/);
      expect(html).not.toMatch(/joining code|meeting code|meeting link|meeting reference/i);
      // A person: no address, no display name, no list of who was there.
      expect(html).not.toMatch(/[\w.+-]+@[\w.-]+\.\w+/);
      expect(html).not.toMatch(/attendees?[:—-]|attendee list|attendance report:/i);
    });

    it("offers no way for an administrator to answer for a participant", async () => {
      // md/03 §3.1: a consent an employer could write is worth nothing. There is
      // deliberately no picker and no approval control on this card.
      renderAdmin(meetClient());

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));

      expect(meet.queryByRole("checkbox")).toBeNull();
      expect(meet.queryByRole("button", { name: /choose|approve|allow|consent/i })).toBeNull();
    });
  });

  describe("the status word", () => {
    it.each([
      ["pending", /Connected but awaiting consent\./],
      ["eligible", /Eligible\./],
      ["active", /Subscribed\./],
      ["renewal_warning", /Subscription expiring\./],
      ["error", /Failed\./],
    ])("shows the word the API's %s means, and no other", async (sent, pattern) => {
      renderAdmin(
        meetClient({ listIntegrations: vi.fn(() => Promise.resolve([withState(sent)])) }),
      );

      await screen.findByRole("heading", { name: /^google meet/i });
      expect(within(card(/^google meet/i)).getByText(pattern)).toBeVisible();
    });

    it("shows no status line at all when the connection carried no state", async () => {
      // **Nothing is invented.** An absent field is "CAIRN has not recorded
      // this", and a status drawn anyway would read as "fine".
      renderAdmin(meetClient());

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));

      expect(meet.queryByText(/Subscribed\.|Eligible\.|awaiting consent\./)).toBeNull();
    });

    it("says 'Disconnected' from the payload rather than dropping the card", async () => {
      renderAdmin(
        meetClient({
          listIntegrations: vi.fn(() =>
            Promise.resolve([{ ...GOOGLE_MEET, disconnectedAt: "2026-08-01T09:00:00Z" }]),
          ),
        }),
      );

      await screen.findByRole("heading", { name: /^google meet/i });
      expect(within(card(/^google meet/i)).getByText(/^Disconnected\./)).toBeVisible();
    });
  });

  describe("starting the grant", () => {
    it("asks the API where to send the customer, then sends them", async () => {
      const assign = captureMeetNavigation();
      const startGoogleMeetInstall = vi.fn(() => Promise.resolve(MEET_INSTALL));
      renderAdmin(unconnectedMeetClient({ startGoogleMeetInstall }));

      await screen.findByRole("heading", { name: /^google meet$/i });
      await userEvent.click(screen.getByRole("button", { name: /connect google meet/i }));

      expect(startGoogleMeetInstall).toHaveBeenCalledWith(WORKSPACE);
      expect(assign).toHaveBeenCalledWith(MEET_INSTALL.authorizeUrl);
    });

    it("shows the server's own notice and when the link lapses", async () => {
      captureMeetNavigation();
      renderAdmin(unconnectedMeetClient());

      await screen.findByRole("heading", { name: /^google meet$/i });
      await userEvent.click(screen.getByRole("button", { name: /connect google meet/i }));

      const meet = within(card(/^google meet$/i));
      expect(
        await meet.findByText(/does not let CAIRN collect anything on its own/i),
      ).toBeVisible();
      expect(meet.getByText(/this link stops working at/i)).toBeVisible();
    });

    it("says which source failed to start, next to that card", async () => {
      renderAdmin(
        unconnectedMeetClient({
          startGoogleMeetInstall: vi.fn(() => Promise.reject(apiError(503))),
        }),
      );

      await screen.findByRole("heading", { name: /^google meet$/i });
      await userEvent.click(screen.getByRole("button", { name: /connect google meet/i }));

      expect(await within(card(/^google meet$/i)).findByRole("alert")).toBeVisible();
    });

    it("reads the Meet outcome from the Meet parameter and no other", async () => {
      // A third provider sharing one `?oauth=` would put a Meet denial on the
      // Chat card, which is a false statement about which grant was refused.
      renderAdmin(unconnectedMeetClient(), "googleMeet=denied");

      await screen.findByRole("heading", { name: /^google meet$/i });
      const meet = within(card(/^google meet$/i));

      expect(meet.getByText(/nothing was connected/i)).toBeVisible();
      expect(within(card(/^google chat$/i)).queryByText(/nothing was connected/i)).toBeNull();
    });

    it("treats a denial as an answer rather than as a failure", async () => {
      renderAdmin(unconnectedMeetClient(), "googleMeet=denied");

      await screen.findByRole("heading", { name: /^google meet$/i });
      const meet = within(card(/^google meet$/i));

      expect(meet.getByText(/google meet shared nothing with it/i)).toBeVisible();
      expect(meet.queryByRole("alert")).toBeNull();
    });

    it("alerts on a failed round trip and says nothing was connected", async () => {
      renderAdmin(unconnectedMeetClient(), "googleMeet=error");

      await screen.findByRole("heading", { name: /^google meet$/i });

      expect(await within(card(/^google meet$/i)).findByRole("alert")).toHaveTextContent(
        /nothing was connected and nothing is being read/i,
      );
    });

    it("does not promise reading after a successful grant", async () => {
      // The card's default says "CAIRN is not reading anything **yet** — it
      // reads only what is chosen below". Both halves are wrong for Meet: there
      // is nothing to choose, and there is no later reading.
      renderAdmin(meetClient(), "googleMeet=connected");

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));

      expect(meet.getByText(/connecting on its own watches nothing/i)).toBeVisible();
      expect(meet.queryByText(/reads only what is chosen below/i)).toBeNull();
    });

    it("ignores an outcome it does not recognise", async () => {
      // The value is attacker-controllable, and rendering an arbitrary one would
      // put a stranger's words on this screen.
      renderAdmin(unconnectedMeetClient(), "googleMeet=%3Cscript%3E");

      await screen.findByRole("heading", { name: /^google meet$/i });
      const meet = within(card(/^google meet$/i));

      expect(meet.queryByText(/nothing was connected/i)).toBeNull();
      expect(meet.queryByRole("alert")).toBeNull();
    });
  });

  describe("disconnecting", () => {
    it("states all of what it does before it happens", async () => {
      renderAdmin(meetClient());

      await screen.findByRole("heading", { name: /^google meet/i });
      await userEvent.click(
        within(card(/^google meet/i)).getByRole("button", { name: /^disconnect$/i }),
      );

      const confirmation = screen.getByRole("group", { name: /disconnect google meet/i });
      expect(confirmation).toHaveTextContent(/tears down the event subscriptions/i);
      expect(confirmation).toHaveTextContent(/destroys the refresh token/i);
      expect(confirmation).toHaveTextContent(/does not delete what has already been recorded/i);
    });

    it("disconnects only after the reader has confirmed", async () => {
      const disconnectGoogleMeet = vi.fn(() => Promise.resolve(MEET_DISCONNECTED));
      renderAdmin(meetClient({ disconnectGoogleMeet }));

      await screen.findByRole("heading", { name: /^google meet/i });
      await userEvent.click(
        within(card(/^google meet/i)).getByRole("button", { name: /^disconnect$/i }),
      );
      expect(disconnectGoogleMeet).not.toHaveBeenCalled();

      await userEvent.click(screen.getByRole("button", { name: /disconnect google meet/i }));
      expect(disconnectGoogleMeet).toHaveBeenCalledWith(WORKSPACE);
    });

    it("says which card failed when the disconnect is refused", async () => {
      renderAdmin(meetClient({ disconnectGoogleMeet: vi.fn(() => Promise.reject(apiError(403))) }));

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));
      await userEvent.click(meet.getByRole("button", { name: /^disconnect$/i }));
      await userEvent.click(screen.getByRole("button", { name: /disconnect google meet/i }));

      expect(await meet.findByRole("alert")).toHaveTextContent(/does not have access to that/i);
    });
  });

  describe("who may change it", () => {
    /** The same screen, read by somebody who does not administer it. */
    function renderAsMember(stub: ReturnType<typeof createStubClient>): void {
      const asMember = {
        ...SESSION,
        workspaces: [{ ...SESSION.workspaces[0]!, role: "member" as const }],
      };
      renderRoute(
        <AppLayout>
          <AdminPage />
        </AppLayout>,
        {
          client: meetClient({
            ...stub,
            getSession: vi.fn(() => Promise.resolve(asMember)),
          }),
          route: "/admin",
        },
      );
    }

    it("gives a Member the whole record and none of the controls", async () => {
      renderAsMember(meetClient());

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));

      // Every word of the record, including the boundary and the scope.
      expect(meet.getByText(/CAIRN does not join calls or start recordings/)).toBeVisible();
      expect(meet.getByText("meetings.space.readonly")).toBeVisible();
      // And an explanation of whose job the controls are, rather than silence.
      expect(
        meet.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
      ).toBeVisible();
      expect(meet.queryByRole("button", { name: /connect google meet/i })).toBeNull();
      expect(meet.queryByRole("button", { name: /^disconnect$/i })).toBeNull();
    });
  });

  describe("the states around the card", () => {
    it("announces the connected sources while they load", async () => {
      renderAdmin(meetClient({ listIntegrations: vi.fn(() => new Promise(() => undefined)) }));

      // The skeleton says nothing on its own, so the announcement is the whole
      // of what a screen reader gets while the list is in flight.
      expect(await screen.findByText(/loading the connected sources/i)).toBeInTheDocument();
    });

    it("lists Meet anyway when nothing at all is connected", async () => {
      renderAdmin(meetClient({ listIntegrations: vi.fn(() => Promise.resolve([])) }));

      await screen.findByRole("heading", { name: /^google meet$/i });
      expect(screen.getByText(/cairn captures nothing until a source is connected/i)).toBeVisible();
    });

    it("offers a retry when the sources could not be loaded", async () => {
      const listIntegrations = vi
        .fn()
        .mockRejectedValueOnce(apiError(500))
        .mockResolvedValue([GOOGLE_MEET]);
      renderAdmin(meetClient({ listIntegrations }));

      const retries = await screen.findAllByRole("button", { name: /try again/i });
      await userEvent.click(retries[0]!);

      expect(await screen.findByRole("heading", { name: /^google meet/i })).toBeVisible();
    });

    it("answers a permission refusal rather than reporting a generic failure", async () => {
      renderAdmin(meetClient({ listIntegrations: vi.fn(() => Promise.reject(apiError(403))) }));

      expect(await screen.findByText(/does not have access to that/i)).toBeVisible();
    });

    it("passes an axe audit with the Meet card and its confirmation open", async () => {
      renderAdmin(
        meetClient({ listIntegrations: vi.fn(() => Promise.resolve([withState("active")])) }),
      );

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = card(/^google meet/i);
      await userEvent.click(within(meet).getByRole("button", { name: /^disconnect$/i }));

      // Audited on the card rather than on the whole screen. The page-level
      // audit is `the trust and privacy centre`'s and `connected sources`'; what
      // is new here is this card and its confirmation, and auditing the whole
      // admin screen a fourth time costs a minute to re-prove somebody else's
      // assertions.
      await expect(axe(meet, AXE_OPTIONS)).resolves.toHaveNoViolations();
    });
  });

  describe("the Trust page's record of it", () => {
    /** Enough of the Trust payload for the page to render around the record. */
    const MEET_TRUST: Trust = {
      sources: [
        {
          source: "google_meet",
          label: "Google Meet",
          reads: "That a transcript exists, for a meeting everybody in it agreed to.",
          connected: false,
        },
      ],
      refusals: ["CAIRN never scores or ranks people."],
      commitments: [
        { title: "Everyone sees the same thing", detail: "Roles decide what you can configure." },
      ],
      retentionDays: 90,
      region: "us-central1",
      awaitingNotification: 0,
      subprocessors: [{ title: "Google Cloud (Vertex AI)", detail: "Runs the models." }],
    };

    function renderMeetTrust(overrides = {}): ReturnType<typeof renderRoute> {
      return renderRoute(
        <AppLayout>
          <TrustPage />
        </AppLayout>,
        {
          client: meetClient({ getTrust: vi.fn(() => Promise.resolve(MEET_TRUST)), ...overrides }),
          route: "/trust",
        },
      );
    }

    it("says CAIRN never joins as a bot or a participant", async () => {
      // Stated on the page for the reader who has *not* been asked about a
      // meeting: somebody who heard "CAIRN does meetings" and wants to know
      // whether it has been sitting in their calls.
      renderMeetTrust();

      // Awaited on the sentence rather than on a role query: a `findByRole` scan
      // of this whole page is re-run every 50ms until it resolves, and the
      // sentence is what the test is actually about.
      const boundary = await screen.findAllByText(
        /CAIRN does not join calls or start recordings\. It can only receive a transcript the meeting platform itself created, and only after every participant in that meeting has agreed\./,
      );

      // Said in the Meetings section, where a reader who has not been asked
      // about any meeting will look — not only on the connection card.
      const inMeetings = boundary.some((node) =>
        (node.closest("section")?.textContent ?? "").startsWith("Meetings"),
      );
      expect(inMeetings).toBe(true);
    });

    it("says Google Meet is not live, with its own blocker rather than Chat's", async () => {
      // Chat is blocked by a RESTRICTED scope needing a CASA assessment. Meet's
      // is SENSITIVE and needs Google's OAuth verification alone. Both are said
      // where each is true, and neither weakens the other.
      renderMeetTrust();

      const notLive = await screen.findAllByText(/google meet cannot be connected yet/i);
      const meetings = notLive
        .map((node) => node.closest("section"))
        .find((section) => (section?.textContent ?? "").startsWith("Meetings"));

      expect(meetings?.textContent).toMatch(/OAuth app verification/i);
      expect(meetings?.textContent).toMatch(/nothing is being received from google meet/i);
      // Chat's blocker is not borrowed for Meet. The CASA assessment is named
      // here only as the thing that would apply if CAIRN asked for the Drive
      // permission, which it does not.
      expect(meetings?.textContent).toMatch(
        /does not need an independent CASA security assessment/i,
      );
    });

    it("keeps the Google Chat wording exactly as it was", async () => {
      // Meet's paragraph must not weaken or contradict Chat's. Chat's card still
      // names the restricted scope and the CASA assessment.
      renderMeetTrust({ listIntegrations: vi.fn(() => Promise.resolve([])) });

      await screen.findByRole("heading", { name: /^google chat$/i });
      const chat = within(card(/^google chat$/i));

      expect(chat.getByText(/casa security assessment/i)).toBeVisible();
      expect(chat.getByText(/cannot be connected yet/i)).toBeVisible();
    });

    it("records Meet read-only, with no control on it for anybody", async () => {
      renderMeetTrust();

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));

      expect(meet.getByText("meetings.space.readonly")).toBeVisible();
      expect(meet.queryByRole("button", { name: /connect|disconnect/i })).toBeNull();
      expect(
        meet.getByText(/read-only here because this page is the record, not the control/i),
      ).toBeVisible();
    });

    it("invents no status for a connection that carried none", async () => {
      // The page's whole claim is that its facts are read from the workspace.
      renderMeetTrust();

      await screen.findByRole("heading", { name: /^google meet/i });
      const meet = within(card(/^google meet/i));

      expect(meet.queryByText(/Subscribed\.|Eligible\.|awaiting consent\./)).toBeNull();
      expect(meet.queryByText(/last successful sync/i)).toBeNull();
    });

    it("shows the status the connection did carry", async () => {
      renderMeetTrust({ listIntegrations: vi.fn(() => Promise.resolve([withState("eligible")])) });

      await screen.findByRole("heading", { name: /^google meet/i });
      expect(within(card(/^google meet/i)).getByText(/^Eligible\./)).toBeVisible();
    });

    it("passes an axe audit with the Meet record on the page", async () => {
      const { container } = renderMeetTrust({
        listIntegrations: vi.fn(() => Promise.resolve([withState("active")])),
      });

      await screen.findByRole("heading", { name: /^google meet/i });

      await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
    });
  });
});
