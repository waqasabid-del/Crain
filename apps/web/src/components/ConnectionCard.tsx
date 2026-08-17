"use client";

import type { Integration } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { DescribedError } from "../errors.js";
import utility from "../styles/utility.module.css";
import styles from "./ConnectionCard.module.css";
import { formatDay, formatDayAndTime } from "./dates.js";
import { headingTag, type HeadingLevel } from "./headings.js";
import { InlineProblem } from "./InlineProblem.js";
import { StatusNote } from "./StatusNote.js";

/**
 * One connected source, as a record rather than a toggle.
 *
 * **Nothing here is invented.** A connection card is the closest thing the
 * product has to a receipt for surveillance — it is where somebody checks that
 * CAIRN is reading what it said it would read, and no more. A plausible "Last
 * synced 4 minutes ago" rendered from a field the server never sent would be the
 * single most damaging thing on the screen, because the Trust page's whole claim
 * is that its numbers are read from the workspace. So every optional detail is
 * rendered when the API returns it and *omitted* when it does not: an absent row
 * says "CAIRN has not recorded this", and the surface that hosts the card says
 * so in words (see `AdminPage`'s provenance line).
 *
 * **The state is a word, never a colour.** The palette is monochrome by design,
 * and a state carried by a shade is one a reader with low vision has to guess.
 *
 * Step 32 added the connect half — an OAuth start, the three distinct ways that
 * round trip can come back, and the precise scope display that has to be legible
 * *before* somebody presses it. Google Chat arrives next; the shape stays
 * provider-agnostic and the provider-specific copy is one table, `PROVIDERS`,
 * near the bottom.
 */

/**
 * What the connection is doing, in the four ways it can differ.
 *
 * `revoked` and `error` are distinct on purpose: revoked means somebody at the
 * provider withdrew CAIRN's access, error means the connection exists and is not
 * working. "Reconnect" is the answer to one and "look at the provider" to the
 * other, and collapsing them loses that.
 *
 * Today's API can produce `connected`, `disconnected` and `error` only — see
 * `connectionFromIntegration`. Nothing renders `revoked` until a field says so.
 */
export type ConnectionState = "connected" | "disconnected" | "revoked" | "error";

const STATE_LABEL: Record<ConnectionState, string> = {
  connected: "Connected",
  disconnected: "Disconnected",
  revoked: "Access revoked",
  error: "Not working",
};

/** Once disconnected or revoked there is nothing left to disconnect. */
const LIVE_STATES: ConnectionState[] = ["connected", "error"];

export interface Connection {
  /** Stable across reloads, so React does not reuse one provider's card for
   * another's when the list reorders. */
  id: string;
  /** "GitHub", not "github". */
  provider: string;
  /**
   * The organisation or workspace on the provider's side.
   *
   * Optional because a source nobody has connected yet does not have one, and
   * the card for it must not invent a name to fill the slot. See
   * `slackNotConnected`.
   */
  account?: string;
  state: ConnectionState;
  /** Why it is in that state, in the reader's words. Always present, because a
   * bare state word leaves "Not working" as an unanswerable sentence. */
  stateDetail: string;
  /** What this provider reads — knowledge the client holds, not a server field. */
  reads?: string;
  /** The scopes actually granted. Only ever what the API returned. */
  scopes?: string[];
  /** The provider's own health summary, when there is one. */
  health?: string;
  lastSuccessfulSyncAt?: string;
  authorisedBy?: string;
  connectedAt?: string;
  disconnectedAt?: string;
}

/** Said to a reader whose role may not change this. Absence is not an
 * explanation: a Viewer must be able to tell "not mine to do" from "nobody has
 * done it". */
export const CONNECTION_READ_ONLY_NOTE =
  "An Owner or an Admin of this workspace connects and disconnects sources, in Workspace settings. This is the same record they see.";

/**
 * One permission, named twice.
 *
 * `scope` is the literal string CAIRN sends to the provider and `means` is what
 * it lets CAIRN do. Both, always: the plain sentence is what a reader
 * understands and the literal name is what they can check against the provider's
 * own consent screen and its documentation. Showing only the sentence asks them
 * to take the translation on trust, which is the one thing this surface will not
 * do; showing only the string is a permission dialog nobody can read.
 */
export interface ScopeGrant {
  scope: string;
  means: string;
}

/**
 * How an OAuth round trip came back.
 *
 * Three outcomes, told apart, because the answer to each is different.
 * `denied` is not a failure — somebody was asked for permission and said no,
 * which is the system working. Collapsing it into `error` produces an apology
 * for a decision the reader made deliberately, and teaches them that saying no
 * broke something.
 */
export type OAuthReturn = "connected" | "denied" | "error";

export interface ConnectionCardProps {
  connection: Connection;
  /** Where the card sits under the page's `<h1>`. Default 3, which is right
   * inside a `Section`. */
  headingLevel?: HeadingLevel;
  /** Owners and Admins. What is *offered* is decided by role; what is *allowed*
   * is decided by the API, which refuses regardless. */
  canManage: boolean;
  /** Overridable for a surface where a different role decides. */
  readOnlyNote?: ReactNode;
  /** Called only after the reader has confirmed. */
  onDisconnect?: () => void;
  disconnecting?: boolean;
  /** A failed disconnect, said where the reader is looking. */
  problem?: DescribedError;

  /**
   * Where an OAuth grant begins.
   *
   * A button, not a link, because the URL does not exist until it is asked for.
   * `POST .../slack/install` mints a single-use `state` nonce and answers with
   * the authorise URL rather than a 302 — a redirect would be followed by
   * `fetch` inside the credentialed request, and the customer would never see
   * Slack's consent screen at all. So the handler calls the API and then moves
   * the window itself.
   *
   * The cost of that is real and is paid deliberately: middle-click, "open in a
   * new tab" and a screen reader's list of links do not work on a button. None
   * of them would have worked here anyway — a `state` nonce is single-use, so a
   * URL opened twice is a URL that fails the second time.
   */
  onConnect?: () => void;
  /** A connect request in flight, while the API is minting the authorise URL. */
  connecting?: boolean;
  /** What the provider's consent screen just said. See `OAuthReturn`. */
  oauthReturn?: OAuthReturn;
  /**
   * The permissions CAIRN *asks* for, exactly.
   *
   * Client-side knowledge, and stated as a request rather than as a grant: what
   * was actually granted comes back from the API as `connection.scopes` and is
   * rendered separately. The two are different claims and the card never lets
   * one stand in for the other.
   */
  requestedScopes?: ScopeGrant[];
  /** What CAIRN cannot do, said rather than left to be inferred from a short
   * list of what it can. An absent capability is invisible; a stated one is
   * checkable. */
  refusals?: string[];
  /** The one sentence a reader has to have read before they act. Placed above
   * the controls, not below them. */
  notice?: ReactNode;
  /** What disconnecting actually does, when the default sentence is not the
   * whole truth for this provider. */
  disconnectEffect?: ReactNode;
  /**
   * What is true immediately after a grant, when the provider's own answer is
   * more specific than "connected".
   *
   * Slack's is the `/invite` requirement, Google Chat's is that a connection
   * with no spaces chosen reads nothing. Both are the difference between
   * somebody understanding why nothing is arriving and concluding the product is
   * broken — and neither is true of the other provider, so the card holds
   * neither and is told.
   */
  connectedDetail?: string;
  /** Provider-specific detail that belongs inside the record — the Slack
   * channel picker sits here. */
  children?: ReactNode;
}

export function ConnectionCard({
  connection,
  headingLevel = 3,
  canManage,
  readOnlyNote = CONNECTION_READ_ONLY_NOTE,
  onDisconnect,
  disconnecting = false,
  problem,
  onConnect,
  connecting = false,
  oauthReturn,
  requestedScopes,
  refusals,
  notice,
  disconnectEffect,
  connectedDetail,
  children,
}: ConnectionCardProps): ReactNode {
  const headingId = useId();
  const confirmId = useId();
  const Heading = headingTag(headingLevel);
  const SubHeading = headingTag(subLevel(headingLevel));

  const [confirming, setConfirming] = useState(false);
  const cardRef = useRef<HTMLElement>(null);
  const actionsRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);

  const disconnectable =
    canManage && onDisconnect !== undefined && LIVE_STATES.includes(connection.state);
  const open = confirming && disconnectable;

  // Connecting is offered for anything that is not currently working. "Connect"
  // and "Reconnect" are different words for different situations: a source that
  // was revoked at the provider needs the grant renewing, and calling that
  // "Connect" hides from the reader that it was ever on.
  const connectable = canManage && onConnect !== undefined && connection.state !== "connected";
  const connectLabel =
    connection.state === "disconnected"
      ? `Connect ${connection.provider}`
      : `Reconnect ${connection.provider}`;

  /*
   * Focus follows the confirmation and comes back when it closes.
   *
   * It lands on the group rather than on either button: a screen reader
   * announces the group's name and its description, so the effect is heard
   * before a key is pressed — and nobody is left with Enter armed over a
   * destructive control they have not read yet.
   *
   * On close it returns to the trigger, which React has just re-mounted, so the
   * live node is looked up rather than a stale one restored. The card itself is
   * the fallback for the case where the disconnect succeeded and the trigger is
   * legitimately gone; focus must land somewhere, and "nowhere" sends a keyboard
   * reader back to the top of the document.
   */
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      confirmRef.current?.focus();
      return;
    }
    if (wasOpen.current) {
      wasOpen.current = false;
      const trigger = actionsRef.current?.querySelector<HTMLButtonElement>("button");
      (trigger ?? cardRef.current)?.focus();
    }
  }, [open]);

  const facts = describeFacts(connection);

  return (
    <article className={styles.card} aria-labelledby={headingId} tabIndex={-1} ref={cardRef}>
      <div className={styles.header}>
        <Heading className={styles.name} id={headingId}>
          {connection.provider}
          {/* No account, no em dash and no placeholder: a source nobody has
              connected has no account name, and " — Not connected" in the
              heading would read as the name of the account. */}
          {connection.account !== undefined && (
            <span className={styles.account}> — {connection.account}</span>
          )}
        </Heading>
        {/*
          The state as a word. `--fg-default` against the muted rest carries the
          emphasis, and the emphasis is not the information: the information is
          the word itself (WCAG 1.4.1).
        */}
        <span className={styles.state}>{STATE_LABEL[connection.state]}</span>
      </div>

      <p className={styles.detail}>{connection.stateDetail}</p>
      {connection.reads !== undefined && <p className={styles.reads}>{connection.reads}</p>}

      {oauthReturn !== undefined && (
        <div className={styles.return}>
          <OAuthReturnMessage
            outcome={oauthReturn}
            provider={connection.provider}
            {...(connectedDetail === undefined ? {} : { connectedDetail })}
          />
        </div>
      )}

      {/*
        Above the controls, deliberately. A caveat printed under the button that
        acts on it is one somebody reads after they have already pressed it.
      */}
      {notice !== undefined && <p className={styles.notice}>{notice}</p>}

      {requestedScopes !== undefined && requestedScopes.length > 0 && (
        <div className={styles.block}>
          <SubHeading className={styles.blockHeading}>
            What CAIRN asks {connection.provider} for
          </SubHeading>
          {/*
            Both names for every permission. The sentence is what a reader
            understands; the literal scope string is what they can check against
            the provider's own consent screen. Neither alone is honest — a
            paraphrase asks them to trust the translation, and a bare
            `channels:history` is a permission dialog nobody can read.
          */}
          <dl className={styles.scopes}>
            {requestedScopes.map((grant) => (
              <div className={styles.scopeRow} key={grant.scope}>
                <dt>
                  <code className={styles.scopeName}>{grant.scope}</code>
                </dt>
                <dd>{grant.means}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {refusals !== undefined && refusals.length > 0 && (
        <div className={styles.block}>
          <SubHeading className={styles.blockHeading}>What CAIRN cannot do</SubHeading>
          {/*
            Stated, never inferred. A short list of granted permissions leaves
            the reader to work out the complement of a set they do not know the
            size of, and everybody's guess is "probably more than that".
          */}
          <ul className={styles.refusals}>
            {refusals.map((refusal) => (
              <li key={refusal}>{refusal}</li>
            ))}
          </ul>
        </div>
      )}

      {facts.length > 0 && (
        <dl className={styles.facts}>
          {facts.map((fact) => (
            <div className={styles.factRow} key={fact.term}>
              <dt>{fact.term}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {children !== undefined && <div className={styles.extra}>{children}</div>}

      {(disconnectable || connectable) && (
        <div className={styles.controls} ref={actionsRef}>
          {open ? (
            <div
              className={styles.confirm}
              role="group"
              aria-label={`Disconnect ${connection.provider}`}
              aria-describedby={confirmId}
              tabIndex={-1}
              ref={confirmRef}
            >
              {/*
                The confirmation restates the consequence rather than asking
                "Are you sure?" — a generic prompt is a button people learn to
                click without reading. And it keeps the distinction exact:
                disconnecting stops new collection, it does not delete what was
                already recorded. Those are different requests, and the second
                one is not a side effect of a button labelled Disconnect.
              */}
              <p className={styles.confirmText} id={confirmId}>
                {disconnectEffect ?? (
                  <>
                    Disconnecting stops CAIRN reading anything more from{" "}
                    {connection.account ?? connection.provider}. It does not remove what has already
                    been recorded — that stays as the team&rsquo;s history.
                  </>
                )}
              </p>
              <div className={styles.actions}>
                <Button size="sm" variant="primary" loading={disconnecting} onClick={onDisconnect}>
                  Disconnect {connection.provider}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={disconnecting}
                  onClick={() => {
                    setConfirming(false);
                  }}
                >
                  Keep it connected
                </Button>
              </div>
            </div>
          ) : (
            <div className={styles.actions}>
              {/*
                A button, because there is no URL to link to until the API has
                been asked for one: the install endpoint mints a single-use
                `state` nonce and returns the authorise URL, which the caller
                then navigates to. See `onConnect`.
              */}
              {connectable && (
                <Button size="sm" variant="primary" loading={connecting} onClick={onConnect}>
                  {connectLabel}
                </Button>
              )}
              {disconnectable && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={connecting}
                  onClick={() => {
                    setConfirming(true);
                  }}
                >
                  Disconnect
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {!canManage && <p className={styles.readOnly}>{readOnlyNote}</p>}

      {/* Wrapped rather than given a `className`: the CSS-module map is typed
          `string | undefined`, and the primitive's prop is not. The wrapper owns
          the spacing, which is the only thing the card wanted to say. */}
      {problem !== undefined && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}
    </article>
  );
}

/**
 * The three ways an OAuth round trip ends, told apart.
 *
 * **A denial is not an error.** Somebody was asked for permission and answered
 * no; that is the consent mechanism working exactly as designed. It gets
 * `role="status"` and a sentence with no apology in it, because an alert and a
 * "sorry, something went wrong" would tell the reader their deliberate decision
 * broke the product — which is how people learn to stop reading consent screens.
 *
 * A genuine failure does get `role="alert"`, because the reader has to act on
 * it, and it says plainly that nothing was connected: after a failed OAuth the
 * one thing somebody cannot tell from the screen is whether access was granted
 * anyway.
 */
function OAuthReturnMessage({
  outcome,
  provider,
  connectedDetail,
}: {
  outcome: OAuthReturn;
  provider: string;
  connectedDetail?: string;
}): ReactNode {
  if (outcome === "error") {
    return (
      <InlineProblem
        error={{
          message: `${provider} did not finish authorising CAIRN, so nothing was connected and nothing is being read. Starting again usually works.`,
        }}
      />
    );
  }

  return (
    <StatusNote>
      {outcome === "connected"
        ? `${provider} is connected. CAIRN is not reading anything yet — it reads only what is chosen below.${connectedDetail === undefined ? "" : ` ${connectedDetail}`}`
        : `Nothing was connected. You did not give CAIRN permission, so ${provider} shared nothing with it and there is nothing to undo. You can start again whenever you want to.`}
    </StatusNote>
  );
}

/** One level down from the card's own heading, so the blocks inside it nest
 * rather than sit as siblings of it (WCAG 1.3.1). Clamped at 6, which is as
 * deep as HTML goes. */
function subLevel(level: HeadingLevel): HeadingLevel {
  return level === 6 ? 6 : ((level + 1) as HeadingLevel);
}

// --------------------------------------------------------------------------
// Slack
// --------------------------------------------------------------------------

/**
 * The scopes CAIRN requests from Slack. Exactly these three, and no others.
 *
 * Copied from the app manifest rather than described from memory, and each one
 * says what it actually permits rather than what it is for. `channels:history`
 * is the one that matters: it is read access to messages, and a sentence like
 * "so CAIRN can understand your team's work" would be a description of CAIRN's
 * intent standing in for a description of the permission.
 */
export const SLACK_SCOPES: ScopeGrant[] = [
  {
    scope: "channels:history",
    means: "Read the messages in the public channels the CAIRN app has been invited to.",
  },
  {
    scope: "channels:read",
    means: "List this workspace's public channels, so you can choose which ones CAIRN reads.",
  },
  {
    scope: "users:read",
    means: "Look up who wrote a message, so it can be attributed to a person.",
  },
];

/**
 * What CAIRN cannot do in Slack, stated rather than left to be inferred.
 *
 * Each line is a permission CAIRN does not request, which means Slack itself
 * would refuse the attempt — these are enforced by the grant, not by CAIRN's own
 * good behaviour, and that is the difference worth writing down.
 */
export const SLACK_REFUSALS: string[] = [
  "Post, reply, or react. CAIRN asks for no permission to write anything to Slack, so nothing it does can appear in your workspace.",
  "Read direct messages, private channels, or group DMs. Those need scopes CAIRN does not request, so Slack refuses them.",
  "Add itself to a channel. CAIRN does not request channels:join — somebody has to invite it.",
];

/**
 * **The single most important sentence on the screen.**
 *
 * CAIRN does not request `channels:join`, so the bot receives messages only from
 * public channels it has been invited to. Without this sentence somebody selects
 * four channels, watches nothing arrive, and concludes the product is broken —
 * and they are not wrong to, because from the screen alone that is the only
 * available explanation.
 */
export const SLACK_INVITE_RULE =
  "Slack only sends CAIRN messages from a channel the CAIRN app has been invited to. Choosing a channel here is not enough on its own: somebody has to run /invite @CAIRN in that channel in Slack, or it will stay silent.";

/**
 * What is true the instant Slack is authorised.
 *
 * The grant is not the end of the setup, and this is the difference between
 * somebody understanding why nothing is arriving and concluding the product is
 * broken. Said on the OAuth return, where they are looking, rather than left to
 * the invite rule further down the card.
 */
export const SLACK_CONNECTED_DETAIL =
  "Messages start arriving only after the CAIRN app has been invited to a channel you have chosen — run /invite @CAIRN there in Slack.";

/** No backfill. Said up front, because "we imported your last 90 days" is what
 * people assume a connection does, and discovering otherwise a week later reads
 * as data loss. */
export const SLACK_NO_HISTORY =
  "Choosing a channel starts collection from that moment. CAIRN does not read anything that was said before, and there is no history import.";

/**
 * What disconnecting Slack does, precisely.
 *
 * Three separate facts, because the reader is entitled to all three and they
 * have different answers: collection stops now, the credential is destroyed, and
 * what was already recorded is *not* deleted — it follows the workspace's
 * retention period like everything else. Deleting it is a different request, and
 * not a side effect of a button labelled Disconnect.
 */
export const SLACK_DISCONNECT_EFFECT =
  "Disconnecting stops new collection immediately and deletes the credential CAIRN stored for your Slack workspace, so it cannot read anything more without being authorised again. It does not delete what has already been recorded: that stays, and is removed on this workspace's retention schedule like every other source.";

/**
 * Slack before anybody has connected it.
 *
 * Rendered rather than omitted, so the scopes, the refusals and the invite rule
 * are all readable while the answer is still "no". Consent that is only
 * explained after the OAuth screen is consent to something the reader had not
 * been told; this card is the telling.
 */
export function slackNotConnected(): Connection {
  return {
    id: "slack",
    provider: "Slack",
    state: "disconnected",
    stateDetail: "Not connected, so CAIRN is reading nothing from Slack.",
    reads: PROVIDERS.slack.reads,
  };
}

// --------------------------------------------------------------------------
// Google Chat
// --------------------------------------------------------------------------

/**
 * The scopes CAIRN requests from Google Chat. Exactly these two, and no others.
 *
 * Both are `readonly` and both are stated as what they *permit* rather than what
 * they are for. `chat.messages.readonly` is the one that matters: it is read
 * access to the messages in the spaces the reader selects, and describing it as
 * "so CAIRN can understand your team's work" would put CAIRN's intent where the
 * permission belongs.
 */
export const GOOGLE_CHAT_SCOPES: ScopeGrant[] = [
  {
    scope: "chat.spaces.readonly",
    means:
      "List the spaces the person who authorises CAIRN can see, so you can choose which ones CAIRN reads.",
  },
  {
    scope: "chat.messages.readonly",
    means:
      "Read the messages in the spaces you select. Only those, and only from the moment you select them.",
  },
];

/**
 * What CAIRN cannot do in Google Chat, stated rather than left to be inferred.
 *
 * Each line is a permission CAIRN does not request, so Google itself refuses the
 * attempt — these are enforced by the grant rather than by CAIRN's own good
 * behaviour, and that is the difference worth writing down.
 */
export const GOOGLE_CHAT_REFUSALS: string[] = [
  "Post or reply. CAIRN asks for no permission to write to Google Chat, so nothing it does can appear in a space.",
  "Read your direct messages. CAIRN reads named spaces only; Google does not grant it your DMs and it does not ask for them.",
  "React to a message, or read anybody's reactions.",
  "See what you have read, or whether you have read it. There is no read-state, no presence and no typing indicator.",
  "See who is a member of a space, or when somebody joined or left. CAIRN does not request membership data.",
  "Use anything administrative. CAIRN asks for no admin scope and no organisation-wide access, so it reads through one person's ordinary account and nothing beyond what that account can already see.",
];

/**
 * **The sentence that decides whether any of this can work at all.**
 *
 * The Google Chat API is a Google Workspace API: a personal Gmail account has no
 * Chat spaces to grant and Google refuses the authorisation. Without this line
 * somebody presses Connect, meets an opaque Google error, and has no way to tell
 * a wrong account from a broken product.
 */
export const GOOGLE_CHAT_WORKSPACE_ACCOUNT =
  "A personal Gmail account cannot authorise this. The account you sign in with has to belong to a Google Workspace organisation — Google Chat spaces exist only there, and Google refuses the request from a personal account.";

/**
 * **Google Chat is not live, and this card must never suggest otherwise.**
 *
 * The connect flow is wired end to end — an install route, a callback, a space
 * picker — and it stops dead at Google. `chat.messages.readonly` is a RESTRICTED
 * scope: granting it needs Google's own OAuth verification *and* an independent
 * third-party CASA security assessment, neither of which is complete, so no
 * authorisation can succeed today (`docs/runbooks/connectors.md`, Google Chat).
 *
 * Without this sentence the screen offers a pressable Connect button whose only
 * possible outcome is an opaque Google error, and the reader has no way to tell
 * a wrong account, a broken product and an unfinished approval apart. The
 * control is left in place rather than hidden — it is the real flow, and it is
 * how the connector gets validated — but it is labelled for what it is.
 *
 * It is not shortened. "Coming soon" would be the same claim with the checkable
 * part removed: the scope name and the assessment are the two facts a buyer's
 * governance review can look up.
 */
export const GOOGLE_CHAT_NOT_LIVE =
  "Google Chat cannot be connected yet, and pressing Connect will not work. Reading messages needs the chat.messages.readonly scope, which Google classes as restricted: it requires Google's own OAuth verification and an independent CASA security assessment, and until both are finished Google refuses the authorisation. Nothing is being read from Google Chat, and nothing can be until that is done.";

/** No backfill. Said up front, because "we imported your last 90 days" is what
 * people assume a connection does, and discovering otherwise a week later reads
 * as data loss. */
export const GOOGLE_CHAT_NO_HISTORY =
  "Choosing a space starts collection from that moment. CAIRN does not read anything that was said in it before, and there is no history import.";

/**
 * What is true the instant Google Chat is authorised.
 *
 * A connection with no spaces chosen reads nothing at all — which is the right
 * default and an unexplained silence if nobody says so.
 */
export const GOOGLE_CHAT_CONNECTED_DETAIL =
  "No spaces are chosen yet, so nothing is being read. CAIRN reads a space only once it is selected below.";

/**
 * What disconnecting Google Chat does, precisely.
 *
 * Three separate facts, because the reader is entitled to all three and they
 * have different answers: collection stops now, the credential is destroyed, and
 * what was already recorded is *not* deleted. Deleting it is a different
 * request, and not a side effect of a button labelled Disconnect.
 */
export const GOOGLE_CHAT_DISCONNECT_EFFECT =
  "Disconnecting stops new collection immediately and deletes the Google credential CAIRN stored, so it cannot read anything more without being authorised again. It also ends the subscriptions Google delivers messages through. It does not delete what has already been recorded: that stays, and is removed on this workspace's retention schedule like every other source.";

/**
 * Google Chat before anybody has connected it.
 *
 * Rendered rather than omitted, so the scopes, the refusals and the Workspace
 * account requirement are all readable while the answer is still "no". Consent
 * that is only explained after the Google consent screen is consent to something
 * the reader had not been told; this card is the telling.
 */
export function googleChatNotConnected(): Connection {
  return {
    id: "google_chat",
    provider: "Google Chat",
    state: "disconnected",
    stateDetail: "Not connected, so CAIRN is reading nothing from Google Chat.",
    reads: PROVIDERS.google_chat.reads,
  };
}

/** One row of a connections list: the card's view of a source, and the payload
 * it came from. `integration` is null for a source nobody has connected. */
export interface ConnectionRow {
  source: string;
  connection: Connection;
  integration: Integration | null;
}

/**
 * Every source, connected or not.
 *
 * Slack appears whether or not it is connected, because the scopes it would ask
 * for, the things it could never do, and the invite rule that decides whether
 * any of it works all have to be readable while the answer is still "no".
 * Consent explained after the OAuth screen is consent to something the reader
 * had not been told.
 *
 * Shared by the workspace screen and the Trust page so the two cannot come to
 * disagree about which sources exist — the Trust page's whole claim is that it
 * is showing the same record.
 */
export function connectionRows(integrations: Integration[]): ConnectionRow[] {
  const rows: ConnectionRow[] = integrations.map((integration) => ({
    source: integration.source,
    connection: connectionFromIntegration(integration),
    integration,
  }));

  if (!integrations.some((integration) => integration.source === "slack")) {
    rows.push({ source: "slack", connection: slackNotConnected(), integration: null });
  }

  if (!integrations.some((integration) => integration.source === "google_chat")) {
    rows.push({ source: "google_chat", connection: googleChatNotConnected(), integration: null });
  }

  return rows;
}

/**
 * The rows, built only from what is actually known.
 *
 * No entry is pushed for an absent field. Not "Unknown", not an em dash, not a
 * greyed-out row: each of those is a claim that CAIRN asked and got no answer,
 * and what actually happened is that nothing asked.
 */
function describeFacts(connection: Connection): { term: string; value: ReactNode }[] {
  const facts: { term: string; value: ReactNode }[] = [];

  if (connection.scopes !== undefined) {
    facts.push({ term: "Access granted", value: connection.scopes.join(", ") });
  }
  if (connection.health !== undefined) {
    facts.push({ term: "Health", value: connection.health });
  }
  if (connection.lastSuccessfulSyncAt !== undefined) {
    facts.push({
      term: "Last successful sync",
      value: (
        <time dateTime={connection.lastSuccessfulSyncAt}>
          {formatDayAndTime(connection.lastSuccessfulSyncAt)}
        </time>
      ),
    });
  }
  if (connection.authorisedBy !== undefined) {
    facts.push({ term: "Authorised by", value: connection.authorisedBy });
  }
  if (connection.connectedAt !== undefined) {
    facts.push({
      term: "Authorised on",
      value: <time dateTime={connection.connectedAt}>{formatDay(connection.connectedAt)}</time>,
    });
  }
  if (connection.disconnectedAt !== undefined) {
    facts.push({
      term: "Disconnected on",
      value: (
        <time dateTime={connection.disconnectedAt}>{formatDay(connection.disconnectedAt)}</time>
      ),
    });
  }

  return facts;
}

/**
 * A card-shaped placeholder.
 *
 * The dimensions match the real card so the page does not jump when the list
 * lands — that shift is the reason a fast page still feels unstable. Silent to
 * assistive technology; `ConnectionsLoading` makes the one announcement.
 */
export function ConnectionCardSkeleton(): ReactNode {
  return (
    <div className={styles.skeleton} aria-hidden="true">
      <span className={styles.skeletonLine} />
      <span className={styles.skeletonLine} />
      <span className={styles.skeletonLine} />
    </div>
  );
}

export interface ConnectionsLoadingProps {
  /** What is loading, as a noun phrase. A skeleton announces nothing on its
   * own, so this text is the whole announcement. */
  label: string;
  count?: number;
}

export function ConnectionsLoading({ label, count = 2 }: ConnectionsLoadingProps): ReactNode {
  return (
    <div className={styles.loading} role="status">
      <span className={utility.visuallyHidden}>Loading {label}.</span>
      {Array.from({ length: count }, (_, index) => (
        // Index keys: interchangeable placeholders with no identity or reorder.
        <ConnectionCardSkeleton key={index} />
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
// Reading a connection out of what the API actually sends
// --------------------------------------------------------------------------

/**
 * What each provider reads, in the reader's words.
 *
 * Client-side knowledge rather than a server field, and stated as such: it is
 * the same promise the Trust page makes, so the two must not be able to drift.
 * An unrecognised source falls back to a sentence that claims nothing.
 *
 * `satisfies` rather than an annotation, so `PROVIDERS.slack` and
 * `PROVIDERS.google_chat` are known to exist and the two `…NotConnected`
 * builders cannot be reading an absent key.
 */
const PROVIDERS = {
  github: {
    label: "GitHub",
    reads:
      "Reading commit messages, pull request titles and reviews. Never the contents of your code.",
  },
  slack: {
    label: "Slack",
    reads:
      "Reading messages in the public channels you choose, and who wrote them. Never direct messages, private channels or group DMs.",
  },
  google_chat: {
    label: "Google Chat",
    reads:
      "Reading messages in the spaces you choose, through one Google Workspace account. Never direct messages, never reactions, never who has read what.",
  },
} satisfies Record<string, { label: string; reads: string }>;

/** A lookup that admits it may miss. `PROVIDERS` has known keys; the source
 * name arriving from the API does not. */
function providerFor(source: string): { label: string; reads: string } | undefined {
  const table: Record<string, { label: string; reads: string }> = PROVIDERS;
  return table[source];
}

/**
 * An `Integration` as the card needs it.
 *
 * **Optional details are read defensively.** `Integration` carries six fields
 * today and the design needs eleven; the missing five are being added to the API
 * concurrently. Reading them through a validated lookup means the day the server
 * starts sending `scopes` the card shows scopes, and until then it shows none —
 * which is exactly the rule this component exists to enforce. A hardcoded
 * placeholder would have had to be *removed* later, and placeholders are never
 * removed later.
 */
export function connectionFromIntegration(integration: Integration): Connection {
  const provider = providerFor(integration.source);
  const disconnectedAt = integration.disconnectedAt ?? undefined;

  const connection: Connection = {
    id: `${integration.source}-${String(integration.installationId)}`,
    provider: provider?.label ?? integration.source,
    account: integration.account,
    ...describeState(integration, provider?.reads),
    connectedAt: integration.connectedAt,
  };

  if (provider !== undefined && disconnectedAt === undefined) connection.reads = provider.reads;
  if (disconnectedAt !== undefined) connection.disconnectedAt = disconnectedAt;

  const scopes = asStrings(read(integration, "scopes"));
  if (scopes !== undefined) connection.scopes = scopes;

  const health = asText(read(integration, "health"));
  if (health !== undefined) connection.health = health;

  const lastSync = asText(read(integration, "lastSuccessfulSyncAt"));
  if (lastSync !== undefined) connection.lastSuccessfulSyncAt = lastSync;

  const authorisedBy = asText(read(integration, "authorisedBy"));
  if (authorisedBy !== undefined) connection.authorisedBy = authorisedBy;

  return connection;
}

/** The state and the sentence that explains it, decided together so neither can
 * be rendered without the other. */
function describeState(
  integration: Integration,
  reads: string | undefined,
): { state: ConnectionState; stateDetail: string } {
  if (integration.disconnectedAt != null) {
    return {
      state: "disconnected",
      // Disconnected rows are listed rather than filtered out: a gap in the feed
      // is explained by "GitHub was disconnected on the 4th" and unexplained by
      // silence.
      //
      // The last sentence is the one somebody acts on. Reconnecting is not
      // undoing: nothing said during the gap is ever recovered, because no
      // source CAIRN reads offers a backfill, and a reader who assumes otherwise
      // finds out a week later and reads it as data loss.
      stateDetail:
        "CAIRN is no longer reading from this account. What it recorded before then stays. Connecting it again starts collection from that moment — nothing said while it was disconnected is recovered.",
    };
  }
  if (integration.suspended) {
    // Named per provider. "Suspended on GitHub" printed on a Slack card is a
    // false statement about which system is refusing, and it sends whoever
    // reads it to the wrong admin console.
    const label = providerFor(integration.source)?.label ?? integration.source;
    return {
      state: "error",
      // Each says what is happening and what the person can actually do. The
      // GitHub sentence names GitHub's own console because CAIRN cannot lift a
      // suspension from here, and the general one is conditional on purpose:
      // reconnecting fixes a lapsed or withdrawn grant and fixes nothing else,
      // so it is not promised as a cure for whatever the provider is refusing.
      stateDetail:
        integration.source === "github"
          ? "Suspended on GitHub. Nothing is being read while it stays that way. An owner of the GitHub organisation lifts a suspension in GitHub's own settings — CAIRN cannot do it from here."
          : `${label} has stopped accepting CAIRN's requests. Nothing is being read while it stays that way. If the authorisation lapsed or was withdrawn, reconnecting is what restores it; if not, the answer is at ${label} rather than here.`,
    };
  }
  return {
    state: "connected",
    stateDetail: reads === undefined ? "CAIRN is reading from this account." : "Reading now.",
  };
}

/**
 * One property of the payload, without asserting it exists.
 *
 * The spread is what makes this honest: `integration.scopes` would not compile,
 * and casting to a wider interface would compile by asserting the very thing
 * that is in question. This asks the object what it has.
 */
function read(integration: Integration, name: string): unknown {
  const payload: Record<string, unknown> = { ...integration };
  return payload[name];
}

/**
 * A string the server actually sent, or nothing.
 *
 * Exported because the Slack channel payload is read under the same rule and a
 * second, subtly different copy of "is this worth rendering?" is how one surface
 * starts drawing an empty row the other one omits.
 */
export function asText(value: unknown): string | undefined {
  // An empty string is a field the server sent without a value, and rendering
  // an empty row is the placeholder this component refuses to draw.
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

export function asStrings(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value.filter((item): item is string => typeof item === "string" && item !== "");
  return items.length === 0 ? undefined : items;
}
