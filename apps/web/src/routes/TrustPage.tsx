"use client";

import type {
  GoogleChatSpaceList,
  Integration,
  SlackChannelList,
  SupportScope,
  SupportSession,
  Trust,
} from "@cairn/api-client";
import Link from "next/link";
import { Button } from "@cairn/ui";
import { useCallback, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { describeError, type DescribedError } from "../errors.js";
import {
  ChannelPicker,
  ChannelPickerLoading,
  SpacePicker,
  SpacePickerLoading,
} from "../components/ChannelPicker.js";
import {
  ConnectionCard,
  connectionRows,
  ConnectionsLoading,
  CONNECTION_READ_ONLY_NOTE,
  GOOGLE_CHAT_NOT_LIVE,
  GOOGLE_CHAT_REFUSALS,
  GOOGLE_CHAT_SCOPES,
  GOOGLE_CHAT_WORKSPACE_ACCOUNT,
  SLACK_INVITE_RULE,
  SLACK_REFUSALS,
  SLACK_SCOPES,
} from "../components/ConnectionCard.js";
import { MEETING_BOUNDARY } from "../components/MeetingConsent.js";
import { PageHeader } from "../components/PageHeader.js";
import { Section } from "../components/Section.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./TrustPage.module.css";

/**
 * The Trust & Privacy Center (md/05 §B.6).
 *
 * **A page in the product, not a policy PDF, and open to everybody** — not an
 * administrator's screen. Two audiences and identical content: the engineer
 * deciding each morning whether this thing is on their side, and the buyer whose
 * AI-governance review increasingly gates the purchase. Writing one version for
 * each is how the two come to disagree.
 *
 * **Every number is read from this workspace.** The retention period, which
 * sources are actually connected, how many people are still waiting to be shown
 * the notification. A trust page that states a retention period the product does
 * not apply is the most damaging sentence CAIRN could publish, because its whole
 * audience is people deciding whether the rest is true — so the figure shown here
 * is the one a sweep enforces by deleting.
 *
 * **Nothing on this page is reassurance.** Every line is either something a
 * reader could check by using the product for an afternoon, or a name they can
 * look up. "We take your privacy seriously" would be the first sentence to cut.
 */
export function TrustPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Trust Center" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is nothing to describe.
        </EmptyState>
      </>
    );
  }

  return <WorkspaceTrust workspaceId={activeWorkspace.id} />;
}

function WorkspaceTrust({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Trust> => client.getTrust(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the trust and privacy page");

  if (state.status === "loading") return <LoadingState label="this page" lines={5} />;
  if (state.status === "failed") {
    return (
      <ErrorState title="This page could not be loaded" error={state.error} onRetry={reload} />
    );
  }

  const trust = state.data;
  const sources = trust.sources ?? [];
  const connected = sources.filter((source) => source.connected);

  return (
    <>
      {/* Titled exactly as the sidebar names it. A reader who clicked "Trust
          Center" and arrived at a page headed something else has to work out
          whether they are where they meant to be, and this is the one screen
          that cannot afford a moment of "is this the right page". */}
      <PageHeader
        title="Trust Center"
        description="What CAIRN reads about you, what it will never do with it, and what you control. Everything here is true of this workspace right now — the numbers are read from it, not written into the page."
      />

      <TrustSection
        title="What CAIRN reads"
        description={
          connected.length === 0
            ? "Nothing is connected yet, so CAIRN is reading nothing. Every source it could ever read is listed here anyway, so you can decide about them before they are switched on."
            : "Every source CAIRN can read is listed, including the ones this workspace has not connected."
        }
      >
        <ul className={styles.sources}>
          {sources.map((source) => (
            <li key={source.source} className={styles.source}>
              <div className={styles.sourceHeader}>
                <span className={styles.sourceName}>{source.label}</span>
                <span className={source.connected ? styles.on : styles.off}>
                  {source.connected ? "Connected" : "Not connected"}
                </span>
              </div>
              <p className={styles.sourceReads}>{source.reads}</p>
            </li>
          ))}
        </ul>

        <p className={styles.aside}>
          You can switch off any source for yourself, and it applies to what CAIRN has already
          attributed to you as well as to anything new.{" "}
          <Link className={styles.link} href="/welcome">
            Your sources and choices
          </Link>
          .
        </p>
      </TrustSection>

      <WorkspaceConnections workspaceId={workspaceId} />

      <TrustSection title="What CAIRN never does">
        {/*
          The same list the notification screen shows, from the same place in the
          API. Two hand-maintained lists of promises is one list plus a way for
          the product to start promising different things in different places.
        */}
        <ul className={styles.refusals}>
          {(trust.refusals ?? []).map((refusal) => (
            <li key={refusal}>{refusal}</li>
          ))}
        </ul>
      </TrustSection>

      {/*
        Meetings, on the page whose whole claim is that what it says can be
        checked.

        Stated here rather than left to the consent screens because the reader
        who needs it is the one who has *not* been asked about a meeting: a
        person who has heard "CAIRN can do meetings" and wants to know whether
        something has been sitting in their calls. The answer is no, and it is a
        product boundary rather than a setting — CAIRN has no meeting connector
        at all, and the permission below exists so that one cannot be built
        without it.

        **Agreeing is not what makes CAIRN lawful, and this section must never
        say it is.** md/03 §3.3 records that consent is not a valid basis in an
        employment context because of the power imbalance; the EU basis is
        legitimate interest with a documented assessment, and opt-in controls
        keep that interest proportionate rather than replacing it. The paragraph
        below says exactly that, in the reader's words, because a trust page that
        claimed consent as the basis would be both wrong and a promise nobody
        could keep.

        The list itself is `MEETING_BOUNDARY`, shared with the two consent
        screens. Three hand-maintained copies of a promise is three chances for
        the product to promise different things in different rooms.
      */}
      <TrustSection
        title="Meetings"
        description="CAIRN records no meeting, and no meeting platform connector exists in it. If one is ever built, this is the permission it will have to hold first."
      >
        <ul className={styles.refusals}>
          {MEETING_BOUNDARY.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>

        <p className={styles.aside}>
          Being asked, and being able to refuse, is a safeguard CAIRN applies on top of its lawful
          basis — it is not the basis itself. In the EU that basis is legitimate interest, with a
          documented assessment; controls like this one are what keep it proportionate. Your answer
          is yours either way: nobody in your workspace can give it for you, and nobody is told how
          you answered.{" "}
          <Link className={styles.link} href="/settings">
            Meetings you have been asked about
          </Link>
          .
        </p>
      </TrustSection>

      <TrustSection title="How CAIRN works, in practice">
        <dl className={styles.commitments}>
          {(trust.commitments ?? []).map((commitment) => (
            <div className={styles.commitment} key={commitment.title}>
              <dt className={styles.commitmentTitle}>{commitment.title}</dt>
              <dd className={styles.commitmentDetail}>{commitment.detail}</dd>
            </div>
          ))}
        </dl>
      </TrustSection>

      <TrustSection title="What happens to the data">
        <dl className={styles.facts}>
          <dt>Raw activity is kept for</dt>
          <dd>
            {trust.retentionDays} days, then deleted. That is the messages and payloads CAIRN
            received. What it understood from them — the record of what the team did, and the briefs
            written from it — is kept as the team&rsquo;s own history.
          </dd>

          <dt>Stored in</dt>
          <dd>{trust.region}</dd>

          <dt>Worker notification</dt>
          <dd>
            {trust.awaitingNotification === 0
              ? "Everyone in this workspace has been shown what CAIRN reads and how to switch it off."
              : `${String(trust.awaitingNotification)} ${trust.awaitingNotification === 1 ? "person has" : "people have"} not been shown it yet. CAIRN attributes nothing to somebody until they have seen it.`}
          </dd>
        </dl>
      </TrustSection>

      <SupportHistory workspaceId={workspaceId} />

      <TrustSection
        title="Who else sees it"
        description="Every company that processes your activity, named, with what it sees. A general assurance about partners is not an answer to this question."
      >
        <dl className={styles.commitments}>
          {(trust.subprocessors ?? []).map((item) => (
            <div className={styles.commitment} key={item.title}>
              <dt className={styles.commitmentTitle}>{item.title}</dt>
              <dd className={styles.commitmentDetail}>{item.detail}</dd>
            </div>
          ))}
        </dl>
      </TrustSection>
    </>
  );
}

/**
 * The shared `Section`, with this page's reading measure.
 *
 * `plain` rather than the workspace screen's eyebrow treatment: these headings
 * are sentences a reader is meant to take in, not signposts to scan past.
 *
 * It also retires six hand-written ids from this file. `id="never"` was written
 * here *and* on a second route, and a duplicate id makes `aria-labelledby`
 * resolve to whichever element the document reaches first — silently, on the
 * page whose entire claim is that what it says can be checked. `Section` mints
 * its own with `useId`, so a region and the heading that names it stay one
 * decision.
 */
function TrustSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}): ReactNode {
  // Both optional props are spread rather than passed: the CSS-module map is
  // typed `string | undefined` and `exactOptionalPropertyTypes` is on, so an
  // absent value has to arrive as an absent property rather than as `undefined`.
  const className = styles.section;

  return (
    <Section
      title={title}
      {...(className === undefined ? {} : { className })}
      {...(description === undefined ? {} : { description })}
    >
      {children}
    </Section>
  );
}

/**
 * The connections themselves, not a claim about them.
 *
 * The section above lists every source CAIRN *could* read, which is a catalogue.
 * This is the workspace's actual record: which accounts are connected, what was
 * granted, when each last worked, and who authorised it. That is the difference
 * between "we only read what you allow" and a reader being able to check it.
 *
 * Read-only for everybody here, including Owners — the control lives on the
 * workspace screen, and this page is a record. The note says which, because a
 * record with no explanation of where it is changed reads as one nobody can
 * change.
 *
 * Absent fields are absent. A last-sync time invented for a page whose entire
 * claim is that its numbers are read from the workspace would discredit every
 * other line on it.
 */
function WorkspaceConnections({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const { activeRole } = useAuth();
  const load = useCallback(
    (signal: AbortSignal): Promise<Integration[]> =>
      client.listIntegrations(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the connected sources");

  const administers = activeRole === "owner" || activeRole === "admin";
  const readOnlyNote = administers
    ? "You can disconnect this in Workspace settings. It is read-only here because this page is the record, not the control."
    : CONNECTION_READ_ONLY_NOTE;

  return (
    <TrustSection
      title="What is connected right now"
      description="The accounts CAIRN is reading from, as this workspace has them. Everything below is read from the connection; anything CAIRN has not recorded is left out rather than guessed at."
    >
      {state.status === "loading" && <ConnectionsLoading label="the connected sources" />}
      {state.status === "failed" && (
        <ErrorState
          title="The connected sources could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
        />
      )}

      {state.status === "ready" && (
        <>
          {state.data.length === 0 && (
            <p className={styles.lead}>
              Nothing is connected, so CAIRN is reading nothing from this workspace. Each source it
              could read is listed below with what it would ask for.
            </p>
          )}

          <ul className={styles.connections} aria-label="Connections">
            {connectionRows(state.data).map((row) => {
              const { connection } = row;
              const connected = connection.state === "connected";

              return (
                <li key={connection.id}>
                  <ConnectionCard
                    connection={connection}
                    canManage={false}
                    readOnlyNote={readOnlyNote}
                    {...(row.source === "slack"
                      ? {
                          requestedScopes: SLACK_SCOPES,
                          refusals: SLACK_REFUSALS,
                          notice: SLACK_INVITE_RULE,
                          ...(connected
                            ? { children: <SlackChannelRecord workspaceId={workspaceId} /> }
                            : {}),
                        }
                      : row.source === "google_chat"
                        ? {
                            requestedScopes: GOOGLE_CHAT_SCOPES,
                            refusals: GOOGLE_CHAT_REFUSALS,
                            // The record has to say why the answer is "not
                            // connected", and for Google Chat the reason is not
                            // that nobody got round to it: the restricted scope
                            // is unverified and no authorisation can complete.
                            // Said only while it is not connected, so the page
                            // can never carry both that sentence and a live
                            // connection.
                            notice: connected ? (
                              GOOGLE_CHAT_WORKSPACE_ACCOUNT
                            ) : (
                              <>
                                {GOOGLE_CHAT_NOT_LIVE} {GOOGLE_CHAT_WORKSPACE_ACCOUNT}
                              </>
                            ),
                            ...(connected
                              ? { children: <GoogleChatSpaceRecord workspaceId={workspaceId} /> }
                              : {}),
                          }
                        : {})}
                  />
                </li>
              );
            })}
          </ul>
        </>
      )}
    </TrustSection>
  );
}

/**
 * Which Slack channels are being read, as a record rather than a control.
 *
 * Read-only for everybody here, Owners included — this page is the record and
 * the workspace screen is the control. The channel names and the count are
 * whatever the API returned and nothing else: a fact invented on the page whose
 * entire claim is that its numbers are read from the workspace would discredit
 * every other line on it.
 *
 * A failure to load is *not* an error panel here. This is one detail inside a
 * record on a page full of other records, and an alert about a channel list is
 * out of proportion to what a reader of the Trust page came for — so it says
 * what is missing, in a sentence, and leaves the rest of the page intact.
 */
function SlackChannelRecord({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<SlackChannelList> =>
      client.listSlackChannels(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state } = useAsync(load, "load the Slack channels");

  if (state.status === "loading") return <ChannelPickerLoading />;
  if (state.status === "failed") {
    return (
      <p className={styles.readOnly}>
        CAIRN could not read which Slack channels are selected just now, so this record is
        incomplete rather than empty.
      </p>
    );
  }

  return (
    <ChannelPicker
      selection={state.data}
      canManage={false}
      readOnlyNote="An Owner or an Admin chooses these in Workspace settings. It is read-only here because this page is the record, not the control."
    />
  );
}

/**
 * Which Google Chat spaces are being read, and whether they are actually
 * delivering.
 *
 * **Selected is not the same as arriving**, and this page is exactly where that
 * distinction has to hold: a space listed as chosen whose subscription expired
 * is not being read, and a record that omits the subscription state says the
 * opposite of what is true. So the read-only picker renders each chosen space
 * with its state in words — and renders nothing at all for a field the backend
 * did not send. There is no invented renewal date and no invented count here;
 * the last successful delivery is whatever the connection itself recorded, shown
 * by the card above, and absent when CAIRN has not recorded one.
 *
 * A failure to load is not an error panel. This is one detail inside a record on
 * a page full of other records, so it says what is missing in a sentence and
 * leaves the rest of the page intact.
 */
function GoogleChatSpaceRecord({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<GoogleChatSpaceList> =>
      client.listGoogleChatSpaces(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state } = useAsync(load, "load the Google Chat spaces");

  if (state.status === "loading") return <SpacePickerLoading />;
  if (state.status === "failed") {
    return (
      <p className={styles.readOnly}>
        CAIRN could not read which Google Chat spaces are selected just now, so this record is
        incomplete rather than empty.
      </p>
    );
  }

  return (
    <SpacePicker
      spaces={state.data}
      canManage={false}
      readOnlyNote="An Owner or an Admin chooses these in Workspace settings. It is read-only here because this page is the record, not the control."
    />
  );
}

/**
 * Who at CAIRN has asked to look at this workspace, and what they opened.
 *
 * Queried records, never reassurance: a page that says "our staff cannot see
 * your data" is worth less than one that lists the four times they asked and
 * what the workspace said (md/15 §5.2).
 *
 * Visible to every member, including Viewers. A record only managers can read
 * is one the people it concerns have to take on trust.
 */
function SupportHistory({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<SupportSession[]> =>
      client.listSupportSessions(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the support history");

  if (state.status === "loading") return <LoadingState label="the support history" lines={2} />;
  if (state.status === "failed") {
    return (
      <TrustSection title="When CAIRN staff have looked">
        <ErrorState
          title="The support history could not be loaded"
          error={state.error}
          onRetry={reload}
        />
      </TrustSection>
    );
  }

  const sessions = state.data;

  return (
    <TrustSection
      title="When CAIRN staff have looked"
      description={
        sessions.length === 0
          ? "Nobody at CAIRN has asked to look at this workspace. If they ever do, they have to ask an Owner or an Admin first, the access ends by itself, and it appears here whether or not you approve it."
          : "Requests are listed here whether they were approved or refused. CAIRN staff cannot grant themselves access, and access ends by itself."
      }
    >
      {sessions.length > 0 && (
        <ul className={styles.sources}>
          {sessions.map((session) => (
            <SessionRecord
              key={session.id}
              session={session}
              workspaceId={workspaceId}
              onChanged={reload}
            />
          ))}
        </ul>
      )}
    </TrustSection>
  );
}

/**
 * One request, told in order: what was asked for, by whom, what this workspace
 * decided, how long it lasted, and what was actually opened.
 *
 * Written as separate sentences rather than one concatenated line because the
 * previous version ran them together and the adjacency did the lying — "Decided
 * by Alice. Ended early." reads as Alice ending it, whoever actually did.
 */
function SessionRecord({
  session,
  workspaceId,
  onChanged,
}: {
  session: SupportSession;
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  const events = session.events ?? [];

  return (
    <li className={styles.source}>
      <div className={styles.sourceHeader}>
        <span className={styles.sourceName}>{describe(session)}</span>
        <span className={session.active ? styles.on : styles.off}>{statusLabel(session)}</span>
      </div>

      <dl className={styles.record}>
        <div className={styles.recordRow}>
          <dt>Asked by</dt>
          <dd>
            {session.requestedBy} on {formatDate(session.requestedAt)}
          </dd>
        </div>
        <div className={styles.recordRow}>
          <dt>Reason given</dt>
          <dd>{session.reason}</dd>
        </div>
        <div className={styles.recordRow}>
          <dt>Asked for</dt>
          <dd>
            {scopeName(session.requestedScope)}, for up to {durationLabel(session.requestedMinutes)}
          </dd>
        </div>

        {/* Field names, never statuses. The badge above already states the
            outcome, and repeating its exact words here made the same sentence
            appear twice on one row. */}
        {session.decidedAt != null && (
          <div className={styles.recordRow}>
            <dt>Decision</dt>
            <dd>
              {session.status === "rejected" ? "Refused" : "Approved"} on{" "}
              {formatDate(session.decidedAt)}
              {session.decidedBy != null && ` by ${session.decidedBy}`}
              {session.approvedScope != null && `, for ${scopeName(session.approvedScope)}`}
            </dd>
          </div>
        )}

        {/* Tense follows the clock. "Expires" about a past instant, on a row
            whose badge already says the access finished, is the kind of small
            inaccuracy this page cannot afford. */}
        {session.expiresAt != null && (
          <div className={styles.recordRow}>
            <dt>{isPast(session.expiresAt) ? "Expired" : "Expires"}</dt>
            <dd>{formatDate(session.expiresAt)}</dd>
          </div>
        )}

        {session.revokedAt != null && (
          <div className={styles.recordRow}>
            <dt>Ended before expiry</dt>
            <dd>
              {formatDate(session.revokedAt)}
              {/* Named only when the API returns it. Sessions ended before CAIRN
                  recorded the revoker say so plainly rather than borrowing the
                  approver's name from the row above. */}
              {session.revokedBy != null
                ? ` by ${session.revokedBy}`
                : " — who ended it was not recorded"}
            </dd>
          </div>
        )}

        <div className={styles.recordRow}>
          <dt>Emergency access</dt>
          <dd>{session.breakGlass ? "Yes — approval was bypassed" : "No"}</dd>
        </div>
      </dl>

      <Decision session={session} workspaceId={workspaceId} onChanged={onChanged} />

      <div className={styles.opened}>
        <h3 className={styles.openedHeading}>What was opened</h3>
        {events.length === 0 ? (
          <p className={styles.openedNone}>
            {session.approvedScope == null
              ? "Nothing — this was never approved."
              : "Nothing. Access was granted and never used."}
          </p>
        ) : (
          <ul className={styles.refusals}>
            {events.map((event, index) => (
              <li key={`${event.occurredAt}-${String(index)}`}>
                {formatDate(event.occurredAt)} — {event.description} ({scopeName(event.scope)})
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

/** What was asked for, in the reader's terms rather than the enum's. */
function describe(session: SupportSession): string {
  return session.requestedScope === "activity_content"
    ? "Access to your team's recorded work"
    : "Access to settings and diagnostics";
}

/**
 * The outcome, stated plainly.
 *
 * A switch rather than a chain of ternaries so that adding a scope or a status
 * on the server is a compile error here. The previous shape defaulted anything
 * unrecognised to "Ended" — a new status would have been reported as finished
 * access on the page whose whole claim is that it does not overstate.
 */
function statusLabel(session: SupportSession): string {
  if (session.active) return "Active now";

  switch (session.status) {
    case "pending":
      return "Waiting for a decision";
    case "rejected":
      return "Refused";
    // Never "ended by you": whoever ended it is named in the record below,
    // where the name can be accurate. The reader may not be that person.
    case "revoked":
      return "Ended early";
    case "approved":
      return "Ended";
    default:
      return assertNever(session.status);
  }
}

function scopeName(scope: SupportScope): string {
  switch (scope) {
    case "activity_content":
      return "your team's recorded work";
    case "configuration_diagnostics":
      return "settings and diagnostics";
    default:
      return assertNever(scope);
  }
}

/** Minutes as a person would say them. */
function durationLabel(minutes: number): string {
  if (minutes < 60) return `${String(minutes)} minutes`;
  const hours = minutes / 60;
  const rounded = Number.isInteger(hours) ? String(hours) : hours.toFixed(1);
  return `${rounded} ${hours === 1 ? "hour" : "hours"}`;
}

function isPast(value: string): boolean {
  return new Date(value).getTime() <= Date.now();
}

/**
 * Turns an unhandled union member into a compile error.
 *
 * Reached only if the server adds a value the client has not been taught, so it
 * returns the raw value rather than throwing: an unfamiliar word on the screen
 * is recoverable, a blank page during a privacy review is not.
 */
function assertNever(value: never): string {
  return String(value);
}

/**
 * Approve, refuse, or end access.
 *
 * Shown only to a role that may actually decide. A control that always fails
 * teaches a reader the product is broken; the API refuses regardless, so this
 * is about not offering a dead end rather than about security.
 */
function Decision({
  session,
  workspaceId,
  onChanged,
}: {
  session: SupportSession;
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const { activeRole } = useAuth();
  // Which action is in flight, not merely whether one is. Sharing a single
  // boolean marked Allow and Refuse as busy together, telling a screen-reader
  // user that two mutually exclusive things were happening at once.
  const [busy, setBusy] = useState<Action | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [confirmingEnd, setConfirmingEnd] = useState(false);

  const mayDecide = activeRole === "owner" || activeRole === "admin";
  const pending = session.status === "pending";
  const actionable = pending || session.active;

  if (!actionable) return null;

  // Read-only readers are told who decides, rather than shown nothing. A Viewer
  // has the same stake in this record as an Owner; silence leaves them unable to
  // tell whether the request is unattended or simply not theirs to act on.
  if (!mayDecide) {
    return (
      <p className={styles.readOnly}>
        {pending
          ? "An Owner or an Admin of this workspace decides this request."
          : "An Owner or an Admin of this workspace can end this access."}
      </p>
    );
  }

  async function run(action: Action, call: () => Promise<unknown>, verb: string): Promise<void> {
    setBusy(action);
    setProblem(null);
    try {
      await call();
      onChanged();
    } catch (error: unknown) {
      setProblem(describeError(error, verb));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.decision}>
      {pending ? (
        <div className={styles.actions}>
          <Button
            size="sm"
            variant="primary"
            loading={busy === "allow"}
            disabled={busy !== null}
            onClick={() => {
              void run(
                "allow",
                () => client.decideSupportSession(workspaceId, session.id, true),
                "approve this request",
              );
            }}
          >
            Allow for {durationLabel(session.requestedMinutes)}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            loading={busy === "refuse"}
            disabled={busy !== null}
            onClick={() => {
              void run(
                "refuse",
                () => client.decideSupportSession(workspaceId, session.id, false),
                "refuse this request",
              );
            }}
          >
            Refuse
          </Button>
        </div>
      ) : confirmingEnd ? (
        // Ending access is not destructive to data, but it is a decision the
        // other party notices, so it states its effect before it happens.
        <div className={styles.actions}>
          <p className={styles.confirm}>
            CAIRN staff lose access to this workspace immediately. The record of what they already
            opened stays here.
          </p>
          <Button
            size="sm"
            variant="primary"
            loading={busy === "end"}
            disabled={busy !== null}
            onClick={() => {
              void run(
                "end",
                () => client.revokeSupportSession(workspaceId, session.id),
                "end this access",
              );
            }}
          >
            End access now
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy !== null}
            onClick={() => {
              setConfirmingEnd(false);
            }}
          >
            Leave it open
          </Button>
        </div>
      ) : (
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setConfirmingEnd(true);
          }}
        >
          End access now
        </Button>
      )}

      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}
    </div>
  );
}

type Action = "allow" | "refuse" | "end";

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
