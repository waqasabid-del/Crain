"use client";

import { ApiError, type Integration } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import clsx from "clsx";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { describeError, type DescribedError } from "../errors.js";
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

/**
 * The state, as a word on the pill.
 *
 * Two of the four are the plain binary a reader is looking for — **Connected**
 * or **Not connected** — and the other two are kept because they are not that
 * binary: a grant somebody withdrew at the provider and a connection that
 * exists and is failing both need a different answer, and rounding either down
 * to "Not connected" would send whoever read it to the wrong place.
 */
const STATE_LABEL: Record<ConnectionState, string> = {
  connected: "Connected",
  disconnected: "Not connected",
  revoked: "Access revoked",
  error: "Not working",
};

/**
 * The pill for a source this deployment holds no credentials for.
 *
 * **Not a state of the connection, which is why it is not in `ConnectionState`.**
 * Nothing was tried and nothing failed: an operator has not given this
 * deployment an OAuth client for the provider, so there is nothing here to
 * connect, revoke or fix. It is a fact about the installation of CAIRN, and it
 * borrows the plain pill treatment — no fill, no heavier weight — because it is
 * the calmest thing on the card rather than something to answer.
 */
const NOT_SET_UP_LABEL = "Not set up";

/**
 * Why the action is switched off, in six words.
 *
 * Named per provider, and it names *who*: the reader of this screen is an Owner
 * or an Admin of the workspace, and this is the one connector problem they
 * cannot solve from inside it — the credentials belong to whoever runs this
 * deployment of CAIRN. "Try again later" would be false, and the 5xx apology it
 * used to show ("Something on CAIRN's side failed… Reference: …") was worse:
 * an incident report for a switch nobody has turned on.
 */
export function notSetUpLine(provider: string): string {
  return `Needs ${provider} credentials from your administrator.`;
}

/**
 * The same fact, at the length the record inside the card is written to.
 *
 * Said in full where there is room for it, so the short line on the face is not
 * the only place a reader can find out that nothing is wrong.
 */
export function notSetUpDetail(provider: string): string {
  return (
    `${provider} has not been set up on this CAIRN deployment, so it cannot be connected here. ` +
    "Nothing failed and nothing is being read. Whoever runs this deployment adds the credentials; " +
    "there is nothing to retry until they have."
  );
}

/**
 * A failed Connect, told apart from a failure.
 *
 * **The defensive half of "Not set up".** The card is switched off in advance
 * from the status the screen loaded, but a deployment can lose its credentials
 * between that load and the click, and the install route answers a 503 whose
 * generic rendering is "Something on CAIRN's side failed… Reference: <uuid>".
 * That copy is correct for a 500 and wrong here: nothing on CAIRN's side failed,
 * retrying will not help, and a reference id invites somebody to open a support
 * ticket about a switch that was never turned on.
 *
 * Matched on the status *and* the provider's own problem type, never on prose,
 * and never on the status alone: a 503 from a load balancer is a real outage and
 * must keep the apology and the reference id it comes with. Everything that is
 * not this one bounded case falls through to `describeError` untouched.
 *
 * The result deliberately carries no `requestId`. There is nothing for support
 * to look up.
 */
export function describeConnectFailure(
  error: unknown,
  {
    provider,
    problemType,
    action,
  }: {
    /** "Slack". Named in the sentence, so a Chat failure cannot read as Slack's. */
    provider: string;
    /** The provider's `not-configured` problem type, e.g. `slack-not-configured`. */
    problemType: string;
    /** What was being attempted — "start connecting Slack" — for the fallback. */
    action: string;
  },
): DescribedError {
  if (error instanceof ApiError && error.status === 503 && error.is(problemType)) {
    return { message: notSetUpDetail(provider) };
  }
  return describeError(error, action);
}

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
  /**
   * The same promise in one glanceable line, for the face of the card.
   *
   * A noun phrase rather than a sentence with a tense in it: the card carries
   * one of these whether or not the source is connected, and "Reads your
   * channels" printed under a **Not connected** pill would be a false statement
   * about what is happening right now. `reads` is the full version and lives
   * inside the disclosure with everything else.
   */
  line?: string;
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
  /**
   * Whether this deployment holds OAuth credentials for the provider.
   *
   * **Defaults to `true`, and that default is deliberate.** The flag is read
   * from an API field, and a client that assumed "not set up" whenever it had
   * not been told would print a false and discouraging claim about every
   * deployment whose API is a version behind. Only a `false` the server
   * actually sent switches the control off.
   */
  configured?: boolean;
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
  /**
   * Replaces the default "CAIRN is not reading anything yet — it reads only what
   * is chosen below" on a successful grant.
   *
   * Exists for Google Meet, where the default is wrong twice over: nothing is
   * chosen below, and "not reading anything **yet**" promises reading that this
   * connector never does. Slack and Chat leave it alone, because for them the
   * default is exactly true.
   */
  connectedSummary?: string;
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
  configured = true,
  oauthReturn,
  requestedScopes,
  refusals,
  notice,
  disconnectEffect,
  connectedDetail,
  connectedSummary,
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
  // Offered and switched off, rather than hidden. A missing button is a screen
  // with a hole in it — the reader is left to wonder whether they lack the role,
  // whether the source exists, or whether the page is broken — and the sentence
  // beside it only makes sense next to the control it explains.
  const unavailable = !configured;
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
        <ProviderMark provider={connection.provider} />
        <div className={styles.identity}>
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
            The state as a word, in `StateBadge`'s treatment — weight and border,
            never hue. A green dot here would be the only colour on the screen,
            and a state carried by a shade is one a reader with low vision has to
            guess at (WCAG 1.4.1).
          */}
          <span
            className={clsx(
              styles.pill,
              !unavailable && connection.state === "connected" && styles.pillLive,
              !unavailable &&
                (connection.state === "error" || connection.state === "revoked") &&
                styles.pillAttention,
            )}
            data-state={unavailable ? "not-set-up" : connection.state}
          >
            {unavailable ? NOT_SET_UP_LABEL : STATE_LABEL[connection.state]}
          </span>
        </div>
      </div>

      {/* One line, and the card's whole claim on the face of it. The long form
          is one click away in the record below. */}
      {unavailable ? (
        <p className={styles.line}>{notSetUpLine(connection.provider)}</p>
      ) : (
        connection.line !== undefined && <p className={styles.line}>{connection.line}</p>
      )}

      {oauthReturn !== undefined && (
        <div className={styles.return}>
          <OAuthReturnMessage
            outcome={oauthReturn}
            provider={connection.provider}
            {...(connectedDetail === undefined ? {} : { connectedDetail })}
            {...(connectedSummary === undefined ? {} : { connectedSummary })}
          />
        </div>
      )}

      {/*
        **The prose is moved, not dropped, and it could not have been dropped.**
        These paragraphs are what CAIRN reads and what it refuses to read — the
        product's promise about surveillance, not decoration around a toggle.
        Deleting them would leave the workspace screen asking somebody to
        authorise a grant whose terms are stated nowhere they are looking, which
        is consent to something they were never told.
        So they sit behind a disclosure instead: one click away, in document
        order above the control that acts on them, and in the accessibility tree
        the whole time — `<details>` keeps the content findable by search and
        reachable by a screen reader rather than removing it from the page.

        It is also deliberately *above* the controls. A caveat printed under the
        button that acts on it is one somebody reads after they have pressed it.
      */}
      <details className={styles.record}>
        <summary className={styles.recordSummary}>What CAIRN reads</summary>
        <div className={styles.recordBody}>
          <p className={styles.detail}>
            {unavailable ? notSetUpDetail(connection.provider) : connection.stateDetail}
          </p>
          {connection.reads !== undefined && <p className={styles.reads}>{connection.reads}</p>}

          {notice !== undefined && <p className={styles.notice}>{notice}</p>}

          {requestedScopes !== undefined && requestedScopes.length > 0 && (
            <div className={styles.block}>
              <SubHeading className={styles.blockHeading}>
                What CAIRN asks {connection.provider} for
              </SubHeading>
              {/*
                Both names for every permission. The sentence is what a reader
                understands; the literal scope string is what they can check
                against the provider's own consent screen. Neither alone is
                honest — a paraphrase asks them to trust the translation, and a
                bare `channels:history` is a permission dialog nobody can read.
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
                Stated, never inferred. A short list of granted permissions
                leaves the reader to work out the complement of a set they do not
                know the size of, and everybody's guess is "probably more than
                that".
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
        </div>
      </details>

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
                <Button
                  size="sm"
                  variant="primary"
                  loading={connecting}
                  disabled={unavailable}
                  onClick={onConnect}
                >
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
 * A mark for the source, drawn rather than borrowed.
 *
 * **None of these is anybody's logo.** They are generic glyphs for the *kind* of
 * thing each source is — a commit graph, a channel, a message, a camera — drawn
 * on a 24-unit grid in `currentColor`, so they inherit the monochrome palette
 * and a company's trademarked artwork never ships inside CAIRN's bundle.
 *
 * Decorative, and `aria-hidden` for it: the provider's name sits immediately
 * beside the mark, so announcing the mark as well would only repeat it worse.
 * A source with no glyph falls back to a monogram, the same way `ProjectTile`
 * handles a project it has no picture for.
 */
const MARKS: Record<string, ReactNode> = {
  // A commit graph: a trunk between two commits, and one branch off it.
  github: (
    <>
      <circle cx="7" cy="5" r="2.25" />
      <circle cx="7" cy="19" r="2.25" />
      <circle cx="17" cy="12" r="2.25" />
      <path d="M7 7.25V16.75" />
      <path d="M7 12H14.75" />
    </>
  ),
  // A channel mark: the hash a public room is written with.
  slack: (
    <>
      <path d="M10.5 4.5 8.5 19.5" />
      <path d="M16 4.5 14 19.5" />
      <path d="M4.5 9.5H19.5" />
      <path d="M4.5 14.5H19.5" />
    </>
  ),
  // A message, with the tail that makes it one rather than a box.
  "google chat": (
    <>
      <rect x="3.5" y="4.5" width="17" height="12" rx="3" />
      <path d="M8.5 16.5V20.5L13 16.5" />
    </>
  ),
  // A camera pointed at nothing: Meet is a call CAIRN is told about and never
  // joins, and the glyph is the meeting rather than a participant.
  "google meet": (
    <>
      <rect x="3" y="6.5" width="12.5" height="11" rx="2.5" />
      <path d="M15.5 10.5 21 7.5V16.5L15.5 13.5Z" />
    </>
  ),
};

function ProviderMark({ provider }: { provider: string }): ReactNode {
  const glyph = MARKS[provider.trim().toLowerCase()];

  return (
    <span className={styles.mark} aria-hidden="true">
      {glyph === undefined ? (
        <span className={styles.monogram}>{provider.slice(0, 1).toUpperCase()}</span>
      ) : (
        <svg
          className={styles.glyph}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          focusable="false"
        >
          {glyph}
        </svg>
      )}
    </span>
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
  connectedSummary,
}: {
  outcome: OAuthReturn;
  provider: string;
  connectedDetail?: string;
  connectedSummary?: string;
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
        ? `${provider} is connected. ${connectedSummary ?? "CAIRN is not reading anything yet — it reads only what is chosen below."}${connectedDetail === undefined ? "" : ` ${connectedDetail}`}`
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
    line: PROVIDERS.slack.line,
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
    line: PROVIDERS.google_chat.line,
    reads: PROVIDERS.google_chat.reads,
  };
}

// --------------------------------------------------------------------------
// Google Meet
// --------------------------------------------------------------------------

/**
 * **The sentence that must be read before anything else on the Meet card.**
 *
 * Everybody who hears "CAIRN does meetings" assumes the same thing — a bot in
 * the corner of the call, recording. That assumption is wrong in every part, and
 * a card that leaves it standing has obtained consent to something the reader
 * believed was happening anyway.
 *
 * Three claims, all checkable. CAIRN requests no scope that can create or
 * configure a meeting space, so it cannot cause a recording; it requests no
 * Drive scope, so it cannot fetch the transcript file; and the eligibility gate
 * refuses a meeting unless every expected participant holds a live acceptance.
 * The connector was built in that order deliberately — the permission exists
 * before the capability does.
 */
export const GOOGLE_MEET_BOUNDARY =
  "CAIRN does not join calls or start recordings. It can only receive a transcript the meeting platform itself created, and only after every participant in that meeting has agreed.";

/**
 * The scope CAIRN requests from Google Meet. Exactly one, and no others.
 *
 * `meetings.space.readonly` reads a meeting space's configuration, which is what
 * authorises a Workspace Events subscription on that space. It is the permission
 * to be *told* something happened. It is not the permission to read what
 * happened, and the plain-words half says so rather than describing what CAIRN
 * wants the notification for.
 */
export const GOOGLE_MEET_SCOPES: ScopeGrant[] = [
  {
    scope: "meetings.space.readonly",
    means:
      "Read a meeting space's settings, which is what lets Google tell CAIRN that a transcript exists for a meeting. It does not let CAIRN read one, and it does not let CAIRN change how a meeting is set up.",
  },
];

/**
 * **Reading a transcript is a different permission, and it has not been
 * granted.**
 *
 * A Meet transcript is a file in Google Drive, so retrieving one needs a Drive
 * scope. CAIRN requests none — `drive`, `drive.readonly`, `drive.file` and
 * `drive.appdata` are all on the connector's forbidden list — which means Google
 * refuses the attempt rather than CAIRN declining to make it.
 *
 * Said separately from the scope table because a reader who has just been told
 * CAIRN can be *notified* about a transcript will otherwise assume the reading
 * is the part that was left unsaid.
 */
export const GOOGLE_MEET_TRANSCRIPT_PERMISSION =
  "Fetching the transcript itself would need a further, separate permission — a Google Drive scope, because a Meet transcript is a Drive file. CAIRN does not request one and has not been granted one, so Google refuses to hand it the file. Today CAIRN can only be told that a transcript exists.";

/**
 * What CAIRN cannot do in Google Meet, stated rather than left to be inferred.
 *
 * Every line is a permission the connector refuses to request, so Google itself
 * enforces it. Attendance is the one worth reading twice: Meet attendance lives
 * behind `admin.reports.audit.readonly`, and md/03 §5.4 forbids the analytic
 * outright, so the scope is on the connector's forbidden list rather than merely
 * unused.
 */
export const GOOGLE_MEET_REFUSALS: string[] = [
  "Join a meeting, appear in one, or be seen by anybody in it. There is no CAIRN bot and no CAIRN participant — nothing to admit to the call and nothing to remove from it.",
  "Start, stop, or ask for a recording or a transcript. CAIRN asks for no permission to create or reconfigure a meeting space, so it cannot cause the artifact it is waiting to hear about.",
  "Read a transcript or a recording. Those are Google Drive files and CAIRN requests no Drive permission of any kind.",
  "See who attended, for how long, or whether somebody joined at all. Attendance reports need an admin scope CAIRN refuses to request.",
  "Read your calendar. CAIRN asks for no calendar permission, so it cannot see what meetings you have.",
  "Watch a meeting nobody agreed to. A meeting is watched only once every expected participant has accepted, and one withdrawal stops it.",
];

/**
 * **Google Meet is not live, and this card must never suggest otherwise.**
 *
 * The connect flow is wired end to end and stops at Google's own approval.
 * `meetings.space.readonly` is a *sensitive* scope, so publishing the connector
 * needs Google's OAuth app verification — which is not finished, so no
 * authorisation can succeed today.
 *
 * **It is deliberately not the same blocker as Google Chat's.** Chat's
 * `chat.messages.readonly` is a *restricted* scope and additionally requires an
 * independent CASA security assessment; Meet's does not, today. Writing Chat's
 * sentence here would overstate the blocker, and a governance reader who looked
 * up the scope classification would find the page wrong — on the one screen
 * whose whole claim is that what it says can be checked. The CASA assessment
 * becomes Meet's problem the moment a Drive scope is added for transcript
 * retrieval, which is a launch decision rather than a code change, and that is
 * said too.
 */
export const GOOGLE_MEET_NOT_LIVE =
  "Google Meet cannot be connected yet, and pressing Connect will not work. meetings.space.readonly is a scope Google classes as sensitive, so publishing this connector needs Google's OAuth app verification, and until that is finished Google refuses the authorisation. Unlike Google Chat, this scope does not need an independent CASA security assessment as things stand — that becomes true only if CAIRN ever asks for the Drive permission a transcript would need, and it does not ask for one today. Nothing is being received from Google Meet, and nothing can be until the verification is done.";

/**
 * What is true the instant Google Meet is authorised.
 *
 * A connection on its own watches nothing at all. Every meeting is asked about
 * separately and every participant answers for themselves, so the honest thing
 * to say on the OAuth return is that connecting has not started anything.
 */
export const GOOGLE_MEET_CONNECTED_DETAIL =
  "Connecting on its own watches nothing. Each meeting is asked about separately, everybody invited to it answers for themselves, and CAIRN is told a transcript exists only for a meeting where every one of them agreed.";

/**
 * What disconnecting Google Meet does, precisely.
 *
 * Four facts, because the endpoint reports four: watching stops, the event
 * subscriptions are torn down, the refresh token is destroyed, and what was
 * already recorded is not deleted. The consent decisions are kept as well —
 * which is a fact in CAIRN's favour and against it at once, so it is stated.
 */
export const GOOGLE_MEET_DISCONNECT_EFFECT =
  "Disconnecting stops Google Meet being watched immediately, tears down the event subscriptions Google would announce a transcript through, and destroys the refresh token CAIRN stored, so it cannot be told anything more without being authorised again. It does not delete what has already been recorded: that stays, and is removed on this workspace's retention schedule. The answers people gave about individual meetings are kept too — reconnecting does not re-start anything on its own.";

/**
 * Google Meet before anybody has connected it.
 *
 * Listed rather than omitted, so the boundary sentence, the single scope and the
 * six refusals are readable while the answer is still "no". This is the surface
 * that matters most for Meet: what a reader believes CAIRN does in a meeting is
 * formed long before anybody presses Connect.
 */
export function googleMeetNotConnected(): Connection {
  return {
    id: "google_meet",
    provider: "Google Meet",
    state: "disconnected",
    stateDetail: "Not connected, so CAIRN is receiving nothing from Google Meet.",
    line: PROVIDERS.google_meet.line,
    reads: PROVIDERS.google_meet.reads,
  };
}

/**
 * Where a workspace's Google Meet stands, in one word.
 *
 * **Seven words, and not one of them is inferred.** Every one comes from
 * something the API said: no connection row at all, a `disconnectedAt`, a
 * `suspended` flag, or a subscription state the server sent. A connection that
 * exists with no subscription state on it gets *no line at all* — see
 * `googleMeetStatus`.
 *
 * The vocabulary is deliberately narrow and deliberately unflattering. "Eligible"
 * and "subscribed" are different facts: eligible means everybody agreed,
 * subscribed means Google has an active lease and would actually announce a
 * transcript. A screen that collapsed them would tell somebody their meeting is
 * being watched when the lease had lapsed, or that it is not when it is.
 */
export type GoogleMeetStatus =
  | "not connected"
  | "connected but awaiting consent"
  | "eligible"
  | "subscribed"
  | "subscription expiring"
  | "disconnected"
  | "failed";

/** The word as it is shown. Sentence case, because it is read as a word and not
 * as a badge. */
const MEET_STATUS_LABEL: Record<GoogleMeetStatus, string> = {
  "not connected": "Not connected",
  "connected but awaiting consent": "Connected but awaiting consent",
  eligible: "Eligible",
  subscribed: "Subscribed",
  "subscription expiring": "Subscription expiring",
  disconnected: "Disconnected",
  failed: "Failed",
};

/** What each word means, in a sentence somebody can act on. A bare status word
 * is an unanswerable sentence — the same rule `Connection.stateDetail` follows. */
const MEET_STATUS_DETAIL: Record<GoogleMeetStatus, string> = {
  "not connected":
    "Google Meet has not been connected, so CAIRN is not told anything about any meeting.",
  "connected but awaiting consent":
    "Google Meet is connected, and nothing is being watched. CAIRN watches a meeting only once every person expected in it has agreed, and somebody has not answered yet.",
  eligible:
    "Everybody expected in the meeting agreed, so CAIRN is allowed to be told a transcript was produced for it. Allowed is not the same as watching: watching needs a live subscription at Google, and this connection has not reported one.",
  subscribed:
    "Google holds a live subscription, so it would tell CAIRN if the meeting platform produced a transcript. CAIRN is still not in the call, and still cannot open the transcript.",
  "subscription expiring":
    "Google's subscription is close to lapsing and CAIRN is renewing it. If the renewal fails, Google stops announcing anything and CAIRN is told nothing more about this meeting.",
  disconnected:
    "Google Meet was disconnected, the subscriptions were torn down and the credential was destroyed. Nothing more is announced to CAIRN.",
  failed:
    "Google has stopped accepting CAIRN's requests, so nothing is being announced to it. If the authorisation lapsed or was withdrawn, reconnecting is what restores it.",
};

/**
 * The status word for a workspace's Google Meet, or nothing.
 *
 * **Nothing is the important return value.** A connected Meet with no
 * subscription state on the payload is a connection CAIRN cannot yet say
 * anything about, and the card omits the line rather than rounding it up to
 * "subscribed" — which would tell somebody a meeting is being watched on the
 * strength of a field that was never sent.
 *
 * The subscription fields are read through `read` for the same reason the card's
 * other optional details are: they are being added to `IntegrationResponse`
 * concurrently, and reading them defensively means the day the server starts
 * sending one the card shows it, and until then it shows none.
 */
export function googleMeetStatus(integration: Integration | null): GoogleMeetStatus | null {
  if (integration === null) return "not connected";
  if (integration.disconnectedAt != null) return "disconnected";
  if (integration.suspended) return "failed";

  return normaliseMeetStatus(asText(read(integration, "subscriptionState")));
}

/**
 * When Google's subscription lapses, if the connection says so.
 *
 * Read through the same defensive lookup as the status, and for the same reason:
 * a date CAIRN was not given is a date no screen prints. There is no fallback
 * and no "unknown" — an absent expiry means the line is left out.
 */
export function googleMeetExpiry(integration: Integration | null): string | undefined {
  if (integration === null) return undefined;
  return asText(read(integration, "subscriptionExpiresAt"));
}

/**
 * A server word, mapped to one this card has wording for.
 *
 * An unrecognised value returns nothing rather than being printed raw or rounded
 * up: `SUBSCRIPTION_STATE_UNSPECIFIED` beside a meeting is a string nobody can
 * act on, and guessing which way it leans is the failure this whole component
 * exists to prevent.
 *
 * **"Subscription expiring" comes from the server or not at all.** It is not
 * computed by comparing an expiry date against the clock: how close is too close
 * is the renewal window, the server owns it, and a client that picked its own
 * threshold would raise an alarm about a subscription that is renewing normally.
 */
function normaliseMeetStatus(value: string | undefined): GoogleMeetStatus | null {
  if (value === undefined) return null;
  return MEET_STATUS_WORDS[value.trim().toLowerCase()] ?? null;
}

const MEET_STATUS_WORDS: Record<string, GoogleMeetStatus> = {
  // The consent gate's vocabulary.
  pending: "connected but awaiting consent",
  awaiting_consent: "connected but awaiting consent",
  eligible: "eligible",
  // The subscription lifecycle's.
  active: "subscribed",
  subscribed: "subscribed",
  renewal_warning: "subscription expiring",
  expiring: "subscription expiring",
  // Every way it can be not working. They are one word here because the answer
  // to all of them is the same, and the card's own state row already separates
  // "disconnected" from "not working".
  suspended: "failed",
  expired: "failed",
  deleted: "failed",
  error: "failed",
  failed: "failed",
};

export interface GoogleMeetStatusNoteProps {
  status: GoogleMeetStatus;
  /** When Google's lease lapses, if the server said. Rendered only for the two
   * states where a date changes what the reader should do. */
  expiresAt?: string;
}

/**
 * The status word and the sentence that answers it.
 *
 * A word, never a colour and never an icon: the palette is monochrome by design
 * and a state carried by a shade is one a reader with low vision has to guess
 * (WCAG 1.4.1).
 *
 * Not a live region. It is part of the record the card draws on load, and an
 * announcement fires on every re-render for a fact nobody just changed.
 */
export function GoogleMeetStatusNote({ status, expiresAt }: GoogleMeetStatusNoteProps): ReactNode {
  const dated = status === "subscribed" || status === "subscription expiring";

  return (
    <p className={styles.detail}>
      <strong>{MEET_STATUS_LABEL[status]}.</strong> {MEET_STATUS_DETAIL[status]}
      {dated && expiresAt !== undefined && (
        <>
          {" "}
          Google&rsquo;s subscription lapses on{" "}
          <time dateTime={expiresAt}>{formatDay(expiresAt)}</time> unless it is renewed.
        </>
      )}
    </p>
  );
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

  // Meet is listed for the strongest version of this reason. What somebody
  // believes CAIRN does inside a meeting is formed long before anybody presses
  // Connect, and the belief is wrong in the invasive direction — so the card
  // that corrects it has to be on the screen while the answer is still "no".
  if (!integrations.some((integration) => integration.source === "google_meet")) {
    rows.push({ source: "google_meet", connection: googleMeetNotConnected(), integration: null });
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
    line: "Commit messages, pull request titles, reviews.",
    reads:
      "Reading commit messages, pull request titles and reviews. Never the contents of your code.",
  },
  slack: {
    label: "Slack",
    line: "Messages in the public channels you choose.",
    reads:
      "Reading messages in the public channels you choose, and who wrote them. Never direct messages, private channels or group DMs.",
  },
  google_chat: {
    label: "Google Chat",
    line: "Messages in the spaces you choose.",
    reads:
      "Reading messages in the spaces you choose, through one Google Workspace account. Never direct messages, never reactions, never who has read what.",
  },
  // Not "reading" anything, and the sentence says so in the same slot every
  // other provider uses to say what it reads. Meet is the one source where the
  // reader's prior assumption is *more* invasive than the truth, so the
  // difference has to be stated where the eye is already looking.
  google_meet: {
    label: "Google Meet",
    // Not "reads" anything, in one line as in the long one. Meet is the source
    // where the reader's assumption is *more* invasive than the truth.
    line: "Only told a transcript exists. Never joins a call.",
    reads:
      "Being told that the meeting platform produced a transcript, for a meeting everybody in it agreed to. CAIRN never joins a call, never starts a recording, never opens a transcript and never sees who attended.",
  },
} satisfies Record<string, { label: string; line: string; reads: string }>;

/** A lookup that admits it may miss. `PROVIDERS` has known keys; the source
 * name arriving from the API does not. */
function providerFor(source: string): Provider | undefined {
  const table: Record<string, Provider> = PROVIDERS;
  return table[source];
}

/** What the client knows about a source, as against what the API sends. */
interface Provider {
  label: string;
  line: string;
  reads: string;
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

  // The one-line version is carried whichever state the source is in — it is a
  // noun phrase about what this connector is for, not a claim that anything is
  // being read right now. The full sentence is not: "Reading messages in the
  // channels you choose" under a disconnected source would be false.
  if (provider !== undefined) connection.line = provider.line;
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
  // "Reading now" is false of Google Meet in the direction that matters. A live
  // Meet connection reads nothing: it is only able to be told that a transcript
  // exists, for a meeting everybody in it agreed to. The generic sentence would
  // confirm the exact belief `GOOGLE_MEET_BOUNDARY` exists to correct.
  if (integration.source === "google_meet") {
    return {
      state: "connected",
      stateDetail:
        "Connected, and reading nothing. CAIRN is not in any call — a connection only lets Google tell it that a transcript exists, for a meeting everybody in it has agreed to.",
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
