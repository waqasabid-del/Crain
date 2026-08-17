import type { Integration } from "@cairn/api-client";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { DescribedError } from "../errors.js";
import {
  ConnectionCard,
  connectionFromIntegration,
  connectionRows,
  ConnectionsLoading,
  googleChatNotConnected,
  GOOGLE_CHAT_CONNECTED_DETAIL,
  GOOGLE_CHAT_DISCONNECT_EFFECT,
  GOOGLE_CHAT_REFUSALS,
  GOOGLE_CHAT_SCOPES,
  GOOGLE_CHAT_WORKSPACE_ACCOUNT,
  slackNotConnected,
  SLACK_DISCONNECT_EFFECT,
  SLACK_INVITE_RULE,
  SLACK_REFUSALS,
  SLACK_SCOPES,
  type Connection,
} from "./ConnectionCard.js";

/**
 * The connection card, and the one rule it exists to enforce: **it never renders
 * a fact the API did not give it.**
 *
 * A connection card is the closest thing CAIRN has to a receipt for
 * surveillance. It is where somebody checks that the product is reading what it
 * said it would read and no more, and the Trust page's entire claim is that its
 * numbers are read from the workspace rather than written into the page. A
 * plausible "Last synced 4 minutes ago" rendered from a field the server never
 * sent would therefore not be a cosmetic defect — it would discredit every other
 * line on the page. Two tests below are about that and nothing else.
 *
 * The rest is the ordinary contract of a destructive control: it says what it
 * does before it does it, it is offered only to a role that may use it, it
 * explains itself to a role that may not, and it can be driven entirely from the
 * keyboard without the reader losing their place.
 *
 * Rendered with bare `render`: the card touches no client, session or route, and
 * pulling in the provider tree would make a failure here ambiguous.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

/** Everything the design asks for, present. Individual tests take fields away. */
const FULL: Connection = {
  id: "github-42",
  provider: "GitHub",
  account: "acme-inc",
  state: "connected",
  stateDetail: "Reading now.",
  reads:
    "Reading commit messages, pull request titles and reviews. Never the contents of your code.",
  scopes: ["Commit messages", "Pull request titles", "Reviews"],
  health: "Delivering webhooks normally",
  lastSuccessfulSyncAt: "2026-08-16T09:30:00Z",
  authorisedBy: "ali@acme.example.com",
  connectedAt: "2026-06-01T09:00:00Z",
};

/** What the API actually returns today. */
const INTEGRATION: Integration = {
  source: "github",
  account: "acme-inc",
  installationId: 42,
  connectedAt: "2026-06-01T09:00:00Z",
  disconnectedAt: null,
  suspended: false,
};

const PROBLEM: DescribedError = {
  message: "CAIRN could not reach the server, so it could not disconnect that source.",
};

describe("what a connection card shows", () => {
  it("states the provider, the account and the state in words", () => {
    render(<ConnectionCard connection={FULL} canManage={false} />);

    expect(screen.getByRole("heading", { name: /github — acme-inc/i })).toBeVisible();
    // The word, not a colour: the palette is monochrome and a state carried by
    // a shade is one a reader with low vision has to guess at (WCAG 1.4.1).
    expect(screen.getByText("Connected")).toBeVisible();
  });

  it("names each state rather than leaving the reader to infer it", () => {
    const { rerender } = render(
      <ConnectionCard
        connection={{ ...FULL, state: "revoked", stateDetail: "Access was withdrawn on GitHub." }}
        canManage
      />,
    );
    expect(screen.getByText("Access revoked")).toBeVisible();
    expect(screen.getByText(/access was withdrawn on github/i)).toBeVisible();

    rerender(
      <ConnectionCard
        connection={{ ...FULL, state: "error", stateDetail: "Suspended on GitHub." }}
        canManage
      />,
    );
    expect(screen.getByText("Not working")).toBeVisible();

    rerender(
      <ConnectionCard
        connection={{ ...FULL, state: "disconnected", stateDetail: "No longer reading." }}
        canManage
      />,
    );
    expect(screen.getByText("Disconnected")).toBeVisible();
  });

  it("renders the scopes, the health and the last successful sync it was given", () => {
    render(<ConnectionCard connection={FULL} canManage={false} />);

    expect(screen.getByText(/commit messages, pull request titles, reviews/i)).toBeVisible();
    expect(screen.getByText("Delivering webhooks normally")).toBeVisible();
    expect(screen.getByText("Last successful sync")).toBeVisible();
    // The localised text is the machine's; the ISO value has to survive it.
    expect(screen.getByText("Last successful sync").parentElement?.textContent).toMatch(/2026/);
  });

  it("names who authorised it and when", () => {
    render(<ConnectionCard connection={FULL} canManage={false} />);

    expect(screen.getByText("ali@acme.example.com")).toBeVisible();
    expect(screen.getByText("Authorised on")).toBeVisible();
  });

  it("omits a field the API did not return, rather than inventing one", () => {
    // **The test this component exists for.** Not "Unknown", not an em dash, not
    // a greyed-out row — each of those claims CAIRN asked and got no answer,
    // when what actually happened is that nothing asked.
    const { container } = render(
      <ConnectionCard
        connection={{
          id: FULL.id,
          provider: FULL.provider,
          account: "acme-inc",
          state: FULL.state,
          stateDetail: FULL.stateDetail,
        }}
        canManage={false}
      />,
    );

    expect(screen.queryByText("Last successful sync")).not.toBeInTheDocument();
    expect(screen.queryByText("Access granted")).not.toBeInTheDocument();
    expect(screen.queryByText("Health")).not.toBeInTheDocument();
    expect(screen.queryByText("Authorised by")).not.toBeInTheDocument();
    // Not an empty record either: no dangling term, no "Unknown", no dash.
    expect(container.querySelector("dl")).toBeNull();
    expect(screen.getByRole("article").textContent).not.toMatch(/unknown|not available|n\/a/i);
  });

  it("treats a field the server sent empty as one it did not send", () => {
    // An empty string is a column with no value in it, and an empty row is the
    // placeholder this component refuses to draw. Assigned to a variable first
    // rather than cast: extra properties on a fresh literal would be a compile
    // error, and a cast would assert the very thing under test.
    const extended = { ...INTEGRATION, health: "  ", scopes: [], lastSuccessfulSyncAt: "" };

    render(<ConnectionCard connection={connectionFromIntegration(extended)} canManage={false} />);

    expect(screen.queryByText("Health")).not.toBeInTheDocument();
    expect(screen.queryByText("Access granted")).not.toBeInTheDocument();
    expect(screen.queryByText("Last successful sync")).not.toBeInTheDocument();
  });
});

describe("reading a connection out of today's API", () => {
  it("shows what GitHub reads, and what it never reads", () => {
    render(<ConnectionCard connection={connectionFromIntegration(INTEGRATION)} canManage />);

    expect(screen.getByText(/never the contents of your code/i)).toBeVisible();
  });

  it("shows no scopes or sync time, because the API does not send them yet", () => {
    // Locked in deliberately: when the backend starts returning these, this test
    // fails and whoever wired it looks at the card. That is the right failure —
    // the wrong one is a card quietly showing a scope nobody granted.
    render(<ConnectionCard connection={connectionFromIntegration(INTEGRATION)} canManage />);

    expect(screen.queryByText("Access granted")).not.toBeInTheDocument();
    expect(screen.queryByText("Last successful sync")).not.toBeInTheDocument();
  });

  it("reads a scope list and a sync time the day the API starts sending them", () => {
    const extended = {
      ...INTEGRATION,
      scopes: ["Commit messages", "Reviews"],
      lastSuccessfulSyncAt: "2026-08-16T09:30:00Z",
      authorisedBy: "ali@acme.example.com",
    };

    render(<ConnectionCard connection={connectionFromIntegration(extended)} canManage />);

    expect(screen.getByText(/commit messages, reviews/i)).toBeVisible();
    expect(screen.getByText("Last successful sync")).toBeVisible();
    expect(screen.getByText("ali@acme.example.com")).toBeVisible();
  });

  it("explains a quiet feed rather than hiding a disconnected source", () => {
    // A gap in the feed is explained by "GitHub was disconnected on the 4th" and
    // unexplained by silence.
    const connection = connectionFromIntegration({
      ...INTEGRATION,
      disconnectedAt: "2026-08-04T09:00:00Z",
    });

    render(<ConnectionCard connection={connection} canManage />);

    expect(screen.getByText("Disconnected")).toBeVisible();
    expect(screen.getByText(/no longer reading from this account/i)).toBeVisible();
    expect(screen.getByText("Disconnected on")).toBeVisible();
    // Nothing left to disconnect.
    expect(screen.queryByRole("button", { name: /^disconnect$/i })).not.toBeInTheDocument();
  });

  it("says a suspended installation is not working, not that it is fine", () => {
    const connection = connectionFromIntegration({ ...INTEGRATION, suspended: true });

    render(<ConnectionCard connection={connection} canManage />);

    expect(screen.getByText("Not working")).toBeVisible();
    expect(screen.getByText(/nothing is being read while it stays that way/i)).toBeVisible();
  });
});

describe("disconnecting", () => {
  it("asks first, and states the effect exactly", async () => {
    // The distinction is the whole point: disconnecting stops NEW collection and
    // does not delete what was already recorded. Deleting is a different request
    // about everybody's shared history, and not a side effect of a button
    // labelled Disconnect.
    const onDisconnect = vi.fn();
    render(<ConnectionCard connection={FULL} canManage onDisconnect={onDisconnect} />);

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));

    expect(onDisconnect).not.toHaveBeenCalled();
    expect(screen.getByText(/stops cairn reading anything more from acme-inc/i)).toBeVisible();
    expect(screen.getByText(/does not remove what has already been recorded/i)).toBeVisible();
  });

  it("only calls the client once the reader has confirmed", async () => {
    const onDisconnect = vi.fn();
    render(<ConnectionCard connection={FULL} canManage onDisconnect={onDisconnect} />);

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));
    await userEvent.click(screen.getByRole("button", { name: /disconnect github/i }));

    expect(onDisconnect).toHaveBeenCalledTimes(1);
  });

  it("lets the reader back out", async () => {
    const onDisconnect = vi.fn();
    render(<ConnectionCard connection={FULL} canManage onDisconnect={onDisconnect} />);

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));
    await userEvent.click(screen.getByRole("button", { name: /keep it connected/i }));

    expect(onDisconnect).not.toHaveBeenCalled();
    expect(screen.queryByText(/stops cairn reading anything more/i)).not.toBeInTheDocument();
  });

  it("says so when the disconnect could not be recorded", async () => {
    render(<ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} problem={PROBLEM} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach the server/i);
  });

  it("marks the control busy rather than leaving it apparently idle", async () => {
    render(<ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} disconnecting />);

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));

    expect(screen.getByRole("button", { name: /disconnect github/i })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });
});

describe("what a role is offered", () => {
  it("offers an Owner or Admin the control", () => {
    render(<ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} />);

    expect(screen.getByRole("button", { name: /^disconnect$/i })).toBeVisible();
  });

  it("shows a Member or Viewer the same record, read-only, and says who can change it", () => {
    // Absence is not an explanation. Silence leaves a Viewer unable to tell "not
    // mine to do" from "nobody has done it" — and the record itself is theirs to
    // read, because it is about their own activity.
    render(<ConnectionCard connection={FULL} canManage={false} onDisconnect={vi.fn()} />);

    expect(screen.getByRole("heading", { name: /github — acme-inc/i })).toBeVisible();
    expect(screen.getByText("Delivering webhooks normally")).toBeVisible();
    expect(screen.queryByRole("button", { name: /disconnect/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
    ).toBeVisible();
  });

  it("takes a note for a surface where somebody else decides", () => {
    render(
      <ConnectionCard
        connection={FULL}
        canManage={false}
        readOnlyNote="You can disconnect this on the workspace screen."
      />,
    );

    expect(screen.getByText(/on the workspace screen/i)).toBeVisible();
  });
});

describe("connecting", () => {
  const SLACK: Connection = {
    id: "slack",
    provider: "Slack",
    state: "disconnected",
    stateDetail: "Not connected, so CAIRN is reading nothing from Slack.",
  };

  it("names a source nobody has connected without inventing an account for it", () => {
    render(<ConnectionCard connection={slackNotConnected()} canManage={false} />);

    expect(screen.getByRole("heading", { name: /^slack$/i })).toBeVisible();
    // No em dash, no "—  Not connected" masquerading as the account's name.
    expect(screen.getByRole("heading", { name: /^slack$/i }).textContent).toBe("Slack");
  });

  it("shows every scope in both forms", () => {
    // The literal string is what a reader can check against the provider's own
    // consent screen; the sentence is what they can understand. Neither on its
    // own is honest.
    render(<ConnectionCard connection={SLACK} canManage requestedScopes={SLACK_SCOPES} />);

    for (const grant of SLACK_SCOPES) {
      expect(screen.getByText(grant.scope)).toBeVisible();
      expect(screen.getByText(grant.means)).toBeVisible();
    }
  });

  it("states what CAIRN cannot do", () => {
    render(<ConnectionCard connection={SLACK} canManage refusals={SLACK_REFUSALS} />);

    expect(screen.getByText(/no permission to write anything to slack/i)).toBeVisible();
    expect(screen.getByText(/direct messages, private channels, or group dms/i)).toBeVisible();
  });

  it("puts the notice above the control that acts on it", () => {
    // A caveat printed under the button is one somebody reads after they have
    // already pressed it.
    render(
      <ConnectionCard
        connection={SLACK}
        canManage
        notice={SLACK_INVITE_RULE}
        onConnect={vi.fn()}
      />,
    );

    const notice = screen.getByText(/\/invite @CAIRN/i);
    const connect = screen.getByRole("button", { name: /^connect slack$/i });

    expect(notice.compareDocumentPosition(connect) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("asks the caller to start the grant rather than linking anywhere", async () => {
    // There is no URL to link to until the API has been asked for one: the
    // install endpoint mints a single-use `state` nonce and answers with the
    // authorise URL, because a 302 on a credentialed request would be followed
    // by `fetch` and the consent screen would never appear.
    const onConnect = vi.fn();
    render(<ConnectionCard connection={SLACK} canManage onConnect={onConnect} />);

    expect(screen.queryByRole("link", { name: /connect/i })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^connect slack$/i }));

    expect(onConnect).toHaveBeenCalledTimes(1);
  });

  it("says a connect request is in flight rather than looking idle", () => {
    // A single-use nonce takes a round trip to mint. A button that looks
    // untouched for that round trip is a button somebody presses twice, and the
    // second press invalidates the first link.
    render(<ConnectionCard connection={SLACK} canManage onConnect={vi.fn()} connecting />);

    expect(screen.getByRole("button", { name: /^connect slack$/i })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("calls it Reconnect when the grant existed and stopped working", () => {
    const { rerender } = render(
      <ConnectionCard
        connection={{ ...SLACK, state: "error", stateDetail: "Slack has stopped accepting." }}
        canManage
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /reconnect slack/i })).toBeVisible();

    rerender(
      <ConnectionCard
        connection={{ ...SLACK, state: "revoked", stateDetail: "Access was withdrawn." }}
        canManage
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /reconnect slack/i })).toBeVisible();
  });

  it("offers nothing to connect once it is connected", () => {
    render(
      <ConnectionCard
        connection={{ ...SLACK, state: "connected", stateDetail: "Reading now." }}
        canManage
        onConnect={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /^connect slack$/i })).not.toBeInTheDocument();
  });

  it("offers a Member or Viewer no connect control", () => {
    render(<ConnectionCard connection={SLACK} canManage={false} onConnect={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /^connect slack$/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
    ).toBeVisible();
  });

  it("states the provider's own disconnect consequences, not the generic ones", async () => {
    // Slack's are not GitHub's: the credential is destroyed as well, and what
    // was recorded follows the retention period rather than simply "staying".
    render(
      <ConnectionCard
        connection={{ ...SLACK, state: "connected", stateDetail: "Reading now." }}
        canManage
        onDisconnect={vi.fn()}
        disconnectEffect={SLACK_DISCONNECT_EFFECT}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));

    expect(screen.getByRole("group", { name: /disconnect slack/i })).toHaveAccessibleDescription(
      /deletes the credential cairn stored/i,
    );
    expect(screen.getByText(/retention schedule like every other source/i)).toBeVisible();
  });

  it("renders provider detail handed to it, inside the record", () => {
    render(
      <ConnectionCard
        connection={{ ...SLACK, state: "connected", stateDetail: "Reading now." }}
        canManage
      >
        <p>Reading #general.</p>
      </ConnectionCard>,
    );

    expect(within(screen.getByRole("article")).getByText("Reading #general.")).toBeVisible();
  });
});

describe("coming back from a consent screen", () => {
  const SLACK: Connection = {
    id: "slack",
    provider: "Slack",
    state: "disconnected",
    stateDetail: "Not connected.",
  };

  it("says what happened when it worked", () => {
    render(
      <ConnectionCard
        connection={{ ...SLACK, state: "connected", stateDetail: "Reading now." }}
        canManage
        oauthReturn="connected"
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/slack is connected/i);
  });

  it("treats a denial as an answer rather than a fault", () => {
    // **The decision this component turns on.** Somebody was asked for
    // permission and said no; that is the consent mechanism working. An alert
    // and an apology teach them their deliberate decision broke something.
    render(<ConnectionCard connection={SLACK} canManage oauthReturn="denied" />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/nothing was connected/i);
    expect(screen.getByRole("article").textContent).not.toMatch(/sorry|failed|error|went wrong/i);
  });

  it("reports a real failure as one, and says nothing was connected", () => {
    // After a broken round trip the one thing somebody cannot tell from the
    // screen is whether access was granted anyway.
    render(<ConnectionCard connection={SLACK} canManage oauthReturn="error" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      /did not finish authorising cairn, so nothing was connected/i,
    );
  });

  it("says nothing at all when there was no round trip", () => {
    render(<ConnectionCard connection={SLACK} canManage />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("keyboard and focus", () => {
  it("can be confirmed without a mouse", async () => {
    const onDisconnect = vi.fn();
    render(<ConnectionCard connection={FULL} canManage onDisconnect={onDisconnect} />);

    await userEvent.tab();
    expect(screen.getByRole("button", { name: /^disconnect$/i })).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    // Focus lands on the group, not on either button: the consequence is
    // announced before a key is pressed, and nobody is left with Enter armed
    // over a destructive control they have not read yet.
    expect(screen.getByRole("group", { name: /disconnect github/i })).toHaveFocus();

    await userEvent.tab();
    expect(screen.getByRole("button", { name: /disconnect github/i })).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(onDisconnect).toHaveBeenCalledTimes(1);
  });

  it("describes the group with the effect, so it is heard on focus", async () => {
    render(<ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));

    expect(screen.getByRole("group", { name: /disconnect github/i })).toHaveAccessibleDescription(
      /does not remove what has already been recorded/i,
    );
  });

  it("puts focus back on the control when the confirmation is dismissed", async () => {
    // Without this, cancelling drops a keyboard reader at the top of the
    // document and they have to tab all the way back to where they were.
    render(<ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));
    await userEvent.click(screen.getByRole("button", { name: /keep it connected/i }));

    expect(screen.getByRole("button", { name: /^disconnect$/i })).toHaveFocus();
  });

  it("keeps focus inside the card when the control it was on disappears", async () => {
    // The disconnect succeeded, the parent reloaded, and the trigger is
    // legitimately gone. Focus has to land somewhere; "nowhere" sends a keyboard
    // reader back to the top of the page.
    const { rerender } = render(
      <ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));
    rerender(
      <ConnectionCard
        connection={{ ...FULL, state: "disconnected", stateDetail: "No longer reading." }}
        canManage
        onDisconnect={vi.fn()}
      />,
    );

    expect(screen.getByRole("article")).toHaveFocus();
  });
});

describe("loading", () => {
  it("announces what is loading, since a skeleton says nothing", () => {
    render(<ConnectionsLoading label="the connected sources" />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading the connected sources.");
  });

  it("hides the placeholders themselves from assistive technology", () => {
    const { container } = render(<ConnectionsLoading label="the connected sources" count={3} />);

    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(3);
  });
});

describe("accessibility", () => {
  it("passes an axe audit in its error state", async () => {
    const { container } = render(
      <ConnectionCard
        connection={{ ...FULL, state: "error", stateDetail: "Suspended on GitHub." }}
        canManage
        onDisconnect={vi.fn()}
        problem={{ ...PROBLEM, requestId: "req_01H9" }}
      />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit with the confirmation open", async () => {
    const { container } = render(
      <ConnectionCard connection={FULL} canManage onDisconnect={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit in its error state with everything a Slack card carries", async () => {
    const { container } = render(
      <ConnectionCard
        connection={{
          ...slackNotConnected(),
          state: "error",
          stateDetail: "Slack has stopped accepting CAIRN's requests.",
        }}
        canManage
        onConnect={vi.fn()}
        oauthReturn="error"
        requestedScopes={SLACK_SCOPES}
        refusals={SLACK_REFUSALS}
        notice={SLACK_INVITE_RULE}
        onDisconnect={vi.fn()}
        disconnectEffect={SLACK_DISCONNECT_EFFECT}
        problem={{ ...PROBLEM, requestId: "req_01H9" }}
      />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("nests the blocks under the card's own heading rather than beside it", () => {
    // A sibling `<h3>` inside an `<h3>`'s card makes heading navigation land on
    // the wrong thing and reads as two records (WCAG 1.3.1).
    const { container } = render(
      <ConnectionCard
        connection={slackNotConnected()}
        canManage={false}
        requestedScopes={SLACK_SCOPES}
        refusals={SLACK_REFUSALS}
      />,
    );

    expect(container.querySelectorAll("h3")).toHaveLength(1);
    expect(container.querySelectorAll("h4")).toHaveLength(2);
  });

  it("keeps the record readable as a definition list", () => {
    // Terms and values, not a run-on line: adjacency does the lying otherwise —
    // "Authorised by Ali. Disconnected." reads as Ali disconnecting it.
    const { container } = render(<ConnectionCard connection={FULL} canManage={false} />);

    expect(container.querySelector("dl")?.textContent).toContain("Access granted");
  });
});

/**
 * Google Chat, on the same card.
 *
 * The whole point of Step 33 is that this is *not* a third integration system:
 * the card, the three OAuth outcomes and the confirmation are Slack's, and the
 * only things that differ are the ones that are genuinely different about
 * Google. Three of those are load-bearing and are what this block is for.
 *
 * - **The two scopes, named exactly.** `chat.messages.readonly` is read access
 *   to the messages in the spaces somebody selects, and it has to be legible
 *   *before* they press Connect rather than after Google's consent screen.
 * - **What the grant makes impossible**, stated rather than left to be inferred
 *   from a short list of what it allows. An absent capability is invisible; a
 *   stated one is checkable.
 * - **A personal Gmail account cannot authorise this.** Without that sentence
 *   somebody presses Connect, meets an opaque Google error, and cannot tell a
 *   wrong account from a broken product.
 */
describe("Google Chat on the connection card", () => {
  /** Everything the workspace screen hands the card when Google Chat is off. */
  function googleChatProps(): {
    requestedScopes: typeof GOOGLE_CHAT_SCOPES;
    refusals: string[];
    notice: string;
    disconnectEffect: string;
  } {
    return {
      requestedScopes: GOOGLE_CHAT_SCOPES,
      refusals: GOOGLE_CHAT_REFUSALS,
      notice: GOOGLE_CHAT_WORKSPACE_ACCOUNT,
      disconnectEffect: GOOGLE_CHAT_DISCONNECT_EFFECT,
    };
  }

  /** The card as the Admin screen renders it once Google Chat is authorised. */
  function connected(): Connection {
    return { ...googleChatNotConnected(), state: "connected", stateDetail: "Reading now." };
  }

  it("names both scopes literally and says what each one permits", () => {
    // Both names for every permission: the sentence is what a reader
    // understands, the literal string is what they can check against Google's
    // own consent screen. Neither alone is honest.
    render(
      <ConnectionCard connection={googleChatNotConnected()} canManage {...googleChatProps()} />,
    );

    expect(screen.getByText("chat.spaces.readonly")).toBeVisible();
    expect(
      screen.getByText(/list the spaces the person who authorises cairn can see/i),
    ).toBeVisible();
    expect(screen.getByText("chat.messages.readonly")).toBeVisible();
    expect(screen.getByText(/read the messages in the spaces you select/i)).toBeVisible();
  });

  it("states what CAIRN cannot do, rather than leaving it to be inferred", () => {
    render(
      <ConnectionCard connection={googleChatNotConnected()} canManage {...googleChatProps()} />,
    );

    expect(screen.getByRole("heading", { name: /what cairn cannot do/i })).toBeVisible();
    expect(screen.getByText(/asks for no permission to write to google chat/i)).toBeVisible();
    expect(screen.getByText(/read your direct messages/i)).toBeVisible();
    expect(screen.getByText(/react to a message/i)).toBeVisible();
    expect(screen.getByText(/no read-state, no presence and no typing indicator/i)).toBeVisible();
    expect(screen.getByText(/does not request membership data/i)).toBeVisible();
    expect(screen.getByText(/no admin scope and no organisation-wide access/i)).toBeVisible();
  });

  it("says that a personal Gmail account cannot authorise it, above the button", () => {
    // **The sentence that decides whether pressing Connect can work at all.**
    // Google Chat is a Workspace API; a personal account has no spaces to grant
    // and Google refuses the request. Above the control, because a caveat
    // printed under the button that acts on it is one somebody reads after they
    // have already pressed it.
    render(
      <ConnectionCard
        connection={googleChatNotConnected()}
        canManage
        onConnect={vi.fn()}
        {...googleChatProps()}
      />,
    );

    const notice = screen.getByText(/a personal gmail account cannot authorise this/i);
    expect(notice).toBeVisible();
    expect(notice).toHaveTextContent(/belong to a google workspace organisation/i);

    const button = screen.getByRole("button", { name: /connect google chat/i });
    expect(notice.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("offers Reconnect rather than Connect once a grant has been withdrawn", () => {
    // Different words for different situations: calling a renewal "Connect"
    // hides from the reader that it was ever on.
    render(
      <ConnectionCard
        connection={{
          ...googleChatNotConnected(),
          state: "revoked",
          stateDetail: "The grant was withdrawn at Google.",
        }}
        canManage
        onConnect={vi.fn()}
        {...googleChatProps()}
      />,
    );

    expect(screen.getByRole("button", { name: /reconnect google chat/i })).toBeVisible();
  });

  it("says plainly that a grant worked, and that nothing is being read yet", () => {
    render(
      <ConnectionCard
        connection={connected()}
        canManage
        oauthReturn="connected"
        connectedDetail={GOOGLE_CHAT_CONNECTED_DETAIL}
        {...googleChatProps()}
      />,
    );

    expect(screen.getByText(/google chat is connected/i)).toBeVisible();
    expect(screen.getByText(/no spaces are chosen yet, so nothing is being read/i)).toBeVisible();
  });

  it("treats a denial as an answer rather than as a failure", () => {
    // Somebody was asked for permission and said no. That is the consent
    // mechanism working; an alert and an apology would teach them that
    // declining broke something.
    render(
      <ConnectionCard
        connection={googleChatNotConnected()}
        canManage
        onConnect={vi.fn()}
        oauthReturn="denied"
        {...googleChatProps()}
      />,
    );

    expect(screen.getByText(/nothing was connected/i)).toBeVisible();
    expect(screen.getByText(/google chat shared nothing with it/i)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says a failed round trip connected nothing, and alerts on it", () => {
    render(
      <ConnectionCard
        connection={googleChatNotConnected()}
        canManage
        onConnect={vi.fn()}
        oauthReturn="error"
        {...googleChatProps()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      /google chat did not finish authorising cairn, so nothing was connected/i,
    );
  });

  it("confirms a disconnect by restating exactly what it does", async () => {
    // Three separate facts, because the reader is entitled to all three and
    // they have different answers: collection stops now, the credential is
    // destroyed, and what was already recorded is *not* deleted.
    render(
      <ConnectionCard
        connection={connected()}
        canManage
        onDisconnect={vi.fn()}
        {...googleChatProps()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /^disconnect$/i }));

    const confirmation = screen.getByRole("group", { name: /disconnect google chat/i });
    expect(confirmation).toHaveTextContent(/stops new collection immediately/i);
    expect(confirmation).toHaveTextContent(/deletes the google credential cairn stored/i);
    expect(confirmation).toHaveTextContent(/does not delete what has already been recorded/i);
  });

  it("tells a Viewer who can change it, rather than showing them nothing", () => {
    render(
      <ConnectionCard
        connection={googleChatNotConnected()}
        canManage={false}
        {...googleChatProps()}
      />,
    );

    expect(
      screen.getByText(/an owner or an admin of this workspace connects and disconnects sources/i),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /connect google chat/i })).not.toBeInTheDocument();
    // And they can still read exactly what it would ask for.
    expect(screen.getByText("chat.messages.readonly")).toBeVisible();
  });

  it("passes an axe audit in its error state with everything a Google Chat card carries", async () => {
    const { container } = render(
      <ConnectionCard
        connection={{
          ...googleChatNotConnected(),
          state: "error",
          stateDetail: "Google Chat has stopped accepting CAIRN's requests.",
        }}
        canManage
        onConnect={vi.fn()}
        onDisconnect={vi.fn()}
        oauthReturn="error"
        {...googleChatProps()}
        problem={{ ...PROBLEM, requestId: "req_01H9" }}
      />,
    );

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("lists Google Chat whether or not anybody has connected it", () => {
    // The scopes, the refusals and the Workspace-account requirement have to be
    // readable while the answer is still "no". Consent explained after the
    // consent screen is consent to something the reader had not been told.
    const rows = connectionRows([]);
    const row = rows.find((entry) => entry.source === "google_chat");

    expect(row?.connection.state).toBe("disconnected");
    expect(row?.connection.stateDetail).toMatch(/reading nothing from google chat/i);
    // Nothing invented to fill the account slot for a source nobody connected.
    expect(row?.connection.account).toBeUndefined();
  });
});
