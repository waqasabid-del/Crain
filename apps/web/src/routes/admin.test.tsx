import type {
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
      within(card(/github — acme-inc/i)).getByText(/disconnect this on the workspace screen/i),
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
        screen.getByText(/an owner or an admin chooses these on the workspace screen/i),
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
