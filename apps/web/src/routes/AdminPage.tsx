"use client";

import type {
  GoogleChatInstall,
  GoogleChatSpaceList,
  GoogleMeetInstall,
  Integration,
  IntegrationProvider,
  SlackChannelList,
  SlackInstall,
} from "@cairn/api-client";
import { useSearchParams } from "next/navigation";
import { useCallback, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth, type TenantRole } from "../auth/context.js";
import {
  ChannelPicker,
  ChannelPickerLoading,
  reconcileChannels,
  reconcileSpaces,
  SpacePicker,
  SpacePickerLoading,
} from "../components/ChannelPicker.js";
import {
  ConnectionCard,
  connectionRows,
  ConnectionsLoading,
  describeConnectFailure,
  GOOGLE_CHAT_CONNECTED_DETAIL,
  GOOGLE_CHAT_DISCONNECT_EFFECT,
  GOOGLE_CHAT_NOT_LIVE,
  GOOGLE_CHAT_REFUSALS,
  GOOGLE_CHAT_SCOPES,
  GOOGLE_CHAT_WORKSPACE_ACCOUNT,
  googleMeetExpiry,
  googleMeetStatus,
  GoogleMeetStatusNote,
  GOOGLE_MEET_BOUNDARY,
  GOOGLE_MEET_CONNECTED_DETAIL,
  GOOGLE_MEET_DISCONNECT_EFFECT,
  GOOGLE_MEET_NOT_LIVE,
  GOOGLE_MEET_REFUSALS,
  GOOGLE_MEET_SCOPES,
  GOOGLE_MEET_TRANSCRIPT_PERMISSION,
  SLACK_CONNECTED_DETAIL,
  SLACK_DISCONNECT_EFFECT,
  SLACK_INVITE_RULE,
  SLACK_REFUSALS,
  SLACK_SCOPES,
  type OAuthReturn,
} from "../components/ConnectionCard.js";
import { formatDayAndTime } from "../components/dates.js";
import { PageHeader } from "../components/PageHeader.js";
import { Section } from "../components/Section.js";
import { EmptyState, ErrorState } from "../components/States.js";
import { StatusNote } from "../components/StatusNote.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./AdminPage.module.css";

/**
 * Workspace settings: what CAIRN is connected to.
 *
 * One subject only. People and their roles live on Team, where the reader is
 * already looking at people; this screen is the connectors and nothing else.
 *
 * **What is offered is decided by role; what is allowed is decided by the API.**
 * Hiding a control the server would refuse is courtesy. Relying on that hiding
 * would be the bug, so nothing here is the only thing standing between a Viewer
 * and a connection change.
 */

/** Whether this role may change the workspace's configuration. */
function administers(role: TenantRole | null): boolean {
  return role === "owner" || role === "admin";
}

export function AdminPage(): ReactNode {
  const { activeWorkspace, activeRole } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Workspace settings" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is nothing to administer.
        </EmptyState>
      </>
    );
  }

  return (
    <>
      {/* Named "Workspace settings" rather than "Workspace" so that every screen
          pointing here — the connection cards, both pickers, the Trust page's
          read-only notes — can name a destination the reader will recognise when
          they arrive. The sidebar's shorter "Workspace" is the same place. */}
      <PageHeader title="Workspace settings" description="What CAIRN is connected to." />

      <Integrations workspaceId={activeWorkspace.id} role={activeRole} />
    </>
  );
}

/**
 * The shared `Section`, with this screen's eyebrow treatment.
 *
 * There was a fourth hand-rolled copy of `Section` in this file — same
 * `useId`/`aria-labelledby` wiring, one different margin. The variant exists so
 * the label of a region and the way it is announced stay one decision.
 */
function AdminSection(props: {
  title: string;
  description?: string;
  children: ReactNode;
}): ReactNode {
  return <Section variant="eyebrow" {...props} />;
}

// --------------------------------------------------------------------------
// Integrations
// --------------------------------------------------------------------------

/**
 * What the provider's consent screen just said, out of the URL it came back to.
 *
 * Validated against the three known outcomes rather than passed through: the
 * value is attacker-controllable, and rendering an arbitrary one would put a
 * stranger's word on a page whose entire purpose is that its words are CAIRN's.
 * An unrecognised value is treated as no return at all.
 */
function readOAuthReturn(value: string | null): OAuthReturn | undefined {
  if (value === "connected" || value === "denied" || value === "error") return value;
  return undefined;
}

/**
 * What CAIRN is connected to, and the controls that start and stop it.
 *
 * Everything a card shows is read from the connection: a detail the API has not
 * sent is left out rather than filled in, and the section says so, because
 * otherwise an absent row reads as "fine" rather than as "not recorded".
 *
 * The disconnect failure is tracked per connection, not per section. One shared
 * error message under a list of three cards does not say which of them failed.
 */
function Integrations({
  workspaceId,
  role,
}: {
  workspaceId: string;
  role: TenantRole | null;
}): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Integration[]> =>
      client.listIntegrations(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the connected sources");
  /*
   * Which sources this deployment could connect at all.
   *
   * A second request rather than a field on the first, because the interesting
   * answer is about a source with no connection to hang a field on: a workspace
   * that has never connected Slack has no row anywhere, and "has this deployment
   * been given Slack credentials?" is a question about the installation rather
   * than about the workspace.
   *
   * Its failure is deliberately not shown and deliberately not retried. This is
   * an extra fact about a screen that works without it, and the fallback below
   * is the permissive one — an unanswered question leaves every control exactly
   * as it was. The alternative, switching Connect off because a side request
   * failed, would invent the very "you cannot do this" the field exists to stop
   * being invented.
   */
  const loadProviders = useCallback(
    (signal: AbortSignal): Promise<IntegrationProvider[]> =>
      client.listIntegrationProviders(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state: providerState } = useAsync(
    loadProviders,
    "check which sources this deployment can connect",
  );
  const [problem, setProblem] = useState<{ id: string; error: DescribedError } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // One parameter per provider, read separately. A shared `?oauth=` would put a
  // Google denial on the Slack card, which is a false statement about which
  // grant a reader just refused.
  const search = useSearchParams();
  const slackReturn = readOAuthReturn(search.get("slack"));
  const googleChatReturn = readOAuthReturn(search.get("googleChat"));
  // `googleMeet` is the parameter the Meet callback's 303 actually carries —
  // see the connector's `_back`. A third provider on a shared parameter would
  // put a Meet denial on the Chat card.
  const googleMeetReturn = readOAuthReturn(search.get("googleMeet"));
  const [connecting, setConnecting] = useState<string | null>(null);
  const [install, setInstall] = useState<SlackInstall | null>(null);
  const [googleChatInstall, setGoogleChatInstall] = useState<GoogleChatInstall | null>(null);
  const [googleMeetInstall, setGoogleMeetInstall] = useState<GoogleMeetInstall | null>(null);

  const canManage = administers(role);

  /**
   * Whether a source can be connected on this deployment at all.
   *
   * **`true` unless the server said otherwise.** A source the status did not
   * mention, or a status that never arrived, leaves the card exactly as it was:
   * claiming "Not set up" from an absent answer would print a false and
   * discouraging sentence on a deployment that is set up perfectly well. Only a
   * `configured: false` the API actually sent switches a control off.
   */
  function configuredFor(source: string): boolean {
    if (providerState.status !== "ready") return true;
    const provider = providerState.data.find((item) => item.source === source);
    return provider?.configured ?? true;
  }

  async function disconnect(id: string, installationId: number): Promise<void> {
    setBusyId(id);
    setProblem(null);
    try {
      await client.disconnectGitHub(workspaceId, installationId);
      reload();
    } catch (error: unknown) {
      setProblem({ id, error: describeError(error, "disconnect that source") });
    } finally {
      setBusyId(null);
    }
  }

  async function disconnectSlack(id: string): Promise<void> {
    setBusyId(id);
    setProblem(null);
    try {
      await client.disconnectSlack(workspaceId);
      reload();
    } catch (error: unknown) {
      setProblem({ id, error: describeError(error, "disconnect that source") });
    } finally {
      setBusyId(null);
    }
  }

  /**
   * Ask the API where to send the customer, then send them.
   *
   * Two steps rather than a link, because the URL does not exist until it is
   * asked for: the install endpoint mints a single-use `state` nonce and returns
   * the authorise URL instead of redirecting to it, since a 302 on a credentialed
   * request is followed by `fetch` and the consent screen would never appear.
   *
   * The install is kept after the navigation is asked for, not discarded. If the
   * window has not moved by the time the next paint lands — a blocked
   * navigation, a slow one, somebody coming back — the card says when the link
   * lapses rather than leaving them looking at a button that appears to have
   * done nothing.
   */
  async function connectSlack(id: string): Promise<void> {
    setConnecting(id);
    setProblem(null);
    try {
      const started = await client.startSlackInstall(workspaceId);
      setInstall(started);
      window.location.assign(started.authorizeUrl);
    } catch (error: unknown) {
      setProblem({
        id,
        error: describeConnectFailure(error, {
          provider: "Slack",
          problemType: "slack-not-configured",
          action: "start connecting Slack",
        }),
      });
    } finally {
      setConnecting(null);
    }
  }

  /** The same two steps as Slack's, against Google's consent screen. */
  async function connectGoogleChat(id: string): Promise<void> {
    setConnecting(id);
    setProblem(null);
    try {
      const started = await client.startGoogleChatInstall(workspaceId);
      setGoogleChatInstall(started);
      window.location.assign(started.authorizeUrl);
    } catch (error: unknown) {
      setProblem({
        id,
        error: describeConnectFailure(error, {
          provider: "Google Chat",
          problemType: "google-chat-not-configured",
          action: "start connecting Google Chat",
        }),
      });
    } finally {
      setConnecting(null);
    }
  }

  /** The same two steps again, against Google's consent screen for Meet. */
  async function connectGoogleMeet(id: string): Promise<void> {
    setConnecting(id);
    setProblem(null);
    try {
      const started = await client.startGoogleMeetInstall(workspaceId);
      setGoogleMeetInstall(started);
      window.location.assign(started.authorizeUrl);
    } catch (error: unknown) {
      setProblem({
        id,
        error: describeConnectFailure(error, {
          provider: "Google Meet",
          problemType: "google-meet-not-configured",
          action: "start connecting Google Meet",
        }),
      });
    } finally {
      setConnecting(null);
    }
  }

  async function disconnectGoogleMeet(id: string): Promise<void> {
    setBusyId(id);
    setProblem(null);
    try {
      await client.disconnectGoogleMeet(workspaceId);
      reload();
    } catch (error: unknown) {
      setProblem({ id, error: describeError(error, "disconnect that source") });
    } finally {
      setBusyId(null);
    }
  }

  async function disconnectGoogleChat(id: string): Promise<void> {
    setBusyId(id);
    setProblem(null);
    try {
      await client.disconnectGoogleChat(workspaceId);
      reload();
    } catch (error: unknown) {
      setProblem({ id, error: describeError(error, "disconnect that source") });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AdminSection
      title="Connected sources"
      description="What CAIRN is reading. Disconnecting stops it reading anything more — it does not remove what has already been recorded."
    >
      {/*
        Standing guidance, not a result, so it does not announce itself. It is
        the sentence that makes an omitted row honest: without it, a card with
        no "Last successful sync" reads as a connection that is fine.
      */}
      <div className={styles.note}>
        <StatusNote live={false}>
          Every detail below is read from the connection itself. Anything CAIRN has not recorded is
          left out rather than guessed at.
        </StatusNote>
      </div>

      {state.status === "loading" && <ConnectionsLoading label="the connected sources" />}
      {state.status === "failed" && (
        // A 403 lands here with its own copy — "this account does not have
        // access to that" — so a permission refusal is answered rather than
        // reported as a generic failure.
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
            <p className={styles.note}>
              CAIRN captures nothing until a source is connected. Every source it could read is
              listed below, switched off, with what it would ask for.
              {!canManage && " An Owner or an Admin of this workspace can connect one."}
            </p>
          )}

          <ul className={styles.connections} aria-label="Connected sources">
            {connectionRows(state.data).map((row) => {
              const { connection, integration } = row;
              const failure = problem?.id === connection.id ? problem.error : undefined;
              const connected = connection.state === "connected";

              return (
                <li key={connection.id}>
                  <ConnectionCard
                    connection={connection}
                    canManage={canManage}
                    configured={configuredFor(row.source)}
                    disconnecting={busyId === connection.id}
                    {...(failure === undefined ? {} : { problem: failure })}
                    {...(row.source === "slack"
                      ? slackCardProps({
                          workspaceId,
                          connected,
                          oauthReturn: slackReturn,
                          canManage,
                          connecting: connecting === connection.id,
                          install,
                          onConnect: () => {
                            void connectSlack(connection.id);
                          },
                          onDisconnect: () => {
                            void disconnectSlack(connection.id);
                          },
                        })
                      : row.source === "google_chat"
                        ? googleChatCardProps({
                            workspaceId,
                            connected,
                            oauthReturn: googleChatReturn,
                            canManage,
                            connecting: connecting === connection.id,
                            install: googleChatInstall,
                            onConnect: () => {
                              void connectGoogleChat(connection.id);
                            },
                            onDisconnect: () => {
                              void disconnectGoogleChat(connection.id);
                            },
                          })
                        : row.source === "google_meet"
                          ? googleMeetCardProps({
                              integration,
                              connected,
                              oauthReturn: googleMeetReturn,
                              connecting: connecting === connection.id,
                              install: googleMeetInstall,
                              onConnect: () => {
                                void connectGoogleMeet(connection.id);
                              },
                              onDisconnect: () => {
                                void disconnectGoogleMeet(connection.id);
                              },
                            })
                          : integration === null
                            ? {}
                            : {
                                onDisconnect: (): void => {
                                  void disconnect(connection.id, integration.installationId);
                                },
                              })}
                  />
                </li>
              );
            })}
          </ul>
        </>
      )}
    </AdminSection>
  );
}

/**
 * Everything the Slack card needs, decided in one place.
 *
 * The invite rule lives on the card until Slack is connected and inside the
 * picker afterwards — where it is the server's own sentence rather than this
 * client's copy of it — so it is always on screen exactly once. Twice is how a
 * reader learns to skip it.
 */
function slackCardProps({
  workspaceId,
  connected,
  oauthReturn,
  canManage,
  connecting,
  install,
  onConnect,
  onDisconnect,
}: {
  workspaceId: string;
  connected: boolean;
  oauthReturn: OAuthReturn | undefined;
  canManage: boolean;
  connecting: boolean;
  install: SlackInstall | null;
  onConnect: () => void;
  onDisconnect: () => void;
}): {
  requestedScopes: typeof SLACK_SCOPES;
  refusals: string[];
  disconnectEffect: string;
  connectedDetail: string;
  onConnect: () => void;
  connecting: boolean;
  onDisconnect: () => void;
  oauthReturn?: OAuthReturn;
  notice?: ReactNode;
  children?: ReactNode;
} {
  return {
    requestedScopes: SLACK_SCOPES,
    refusals: SLACK_REFUSALS,
    disconnectEffect: SLACK_DISCONNECT_EFFECT,
    connectedDetail: SLACK_CONNECTED_DETAIL,
    onConnect,
    connecting,
    onDisconnect,
    ...(oauthReturn === undefined ? {} : { oauthReturn }),
    ...(connected ? {} : { notice: connectNotice(install) }),
    ...(connected
      ? { children: <SlackChannels workspaceId={workspaceId} canManage={canManage} /> }
      : {}),
  };
}

/**
 * What to read before authorising, and — once an install has begun — how long
 * the link that was just minted is good for.
 *
 * The sentence is the server's whenever there is one to use: the install
 * response carries the same `/invite` requirement the channel endpoints do, and
 * a client-side copy alongside it is a copy that eventually says something the
 * backend no longer enforces. `SLACK_INVITE_RULE` is only the stand-in for
 * before anybody has asked.
 *
 * The expiry is stated rather than left implicit because a `state` nonce is
 * single-use and time-boxed: somebody who opens the consent screen, goes to
 * lunch and comes back gets a failure whose only explanation is this line.
 */
function connectNotice(install: SlackInstall | null): ReactNode {
  if (install === null) return SLACK_INVITE_RULE;

  return (
    <>
      {install.notice} Sending you to Slack now. This link stops working at{" "}
      <time dateTime={install.expiresAt}>{formatDayAndTime(install.expiresAt)}</time> — if nothing
      happens, or you come back to this later, start again.
    </>
  );
}

/**
 * Everything the Google Chat card needs, decided in one place.
 *
 * The shape is Slack's, deliberately: the same card, the same connect and
 * disconnect controls, the same three OAuth outcomes. What differs is only what
 * is *true* of Google Chat — the two `readonly` scopes, the six things the grant
 * makes impossible, and the Workspace-account requirement, which is the one
 * sentence that decides whether pressing Connect can work at all.
 */
function googleChatCardProps({
  workspaceId,
  connected,
  oauthReturn,
  canManage,
  connecting,
  install,
  onConnect,
  onDisconnect,
}: {
  workspaceId: string;
  connected: boolean;
  oauthReturn: OAuthReturn | undefined;
  canManage: boolean;
  connecting: boolean;
  install: GoogleChatInstall | null;
  onConnect: () => void;
  onDisconnect: () => void;
}): {
  requestedScopes: typeof GOOGLE_CHAT_SCOPES;
  refusals: string[];
  disconnectEffect: string;
  connectedDetail: string;
  notice: ReactNode;
  onConnect: () => void;
  connecting: boolean;
  onDisconnect: () => void;
  oauthReturn?: OAuthReturn;
  children?: ReactNode;
} {
  return {
    requestedScopes: GOOGLE_CHAT_SCOPES,
    refusals: GOOGLE_CHAT_REFUSALS,
    disconnectEffect: GOOGLE_CHAT_DISCONNECT_EFFECT,
    connectedDetail: GOOGLE_CHAT_CONNECTED_DETAIL,
    // Kept on screen whether or not Google Chat is connected: reconnecting needs
    // the same kind of account, and somebody reading the record is entitled to
    // know which kind of account CAIRN is reading through.
    notice: googleChatNotice(install, connected),
    onConnect,
    connecting,
    onDisconnect,
    ...(oauthReturn === undefined ? {} : { oauthReturn }),
    ...(connected
      ? { children: <GoogleChatSpaces workspaceId={workspaceId} canManage={canManage} /> }
      : {}),
  };
}

/**
 * What to read before authorising, and — once an install has begun — how long
 * the link that was just minted is good for.
 *
 * **The unavailability comes first**, because it is the fact that decides
 * whether any of the rest matters: `chat.messages.readonly` is a restricted
 * scope and no authorisation can complete until Google's verification and the
 * CASA assessment are done. It is stated only while the connection is not
 * `connected` — a card describing a live connection must not carry a sentence
 * saying that connection is impossible, whichever of the two turns out to be
 * wrong.
 *
 * The server's own sentence is added when there is one, alongside rather than
 * instead of the account requirement: the two say different things, and the
 * `state` nonce being single-use and time-boxed is exactly the failure whose
 * only explanation is this line.
 */
function googleChatNotice(install: GoogleChatInstall | null, connected: boolean): ReactNode {
  const unavailable = connected ? null : <>{GOOGLE_CHAT_NOT_LIVE} </>;

  if (install === null) {
    return (
      <>
        {unavailable}
        {GOOGLE_CHAT_WORKSPACE_ACCOUNT}
      </>
    );
  }

  return (
    <>
      {unavailable}
      {GOOGLE_CHAT_WORKSPACE_ACCOUNT} {install.notice} Sending you to Google now. This link stops
      working at <time dateTime={install.expiresAt}>{formatDayAndTime(install.expiresAt)}</time> —
      if nothing happens, or you come back to this later, start again.
    </>
  );
}

/**
 * Everything the Google Meet card needs, decided in one place.
 *
 * The card is the same one Slack and Chat use. What is different about Meet is
 * what the reader already believes: that connecting a meeting platform puts a
 * bot in the call. So the boundary sentence sits at the top of the notice —
 * above the connect control, above the scope, above everything — and the single
 * scope is followed immediately by the permission CAIRN does *not* hold.
 *
 * **No picker.** There is deliberately nothing to choose here: a meeting is not
 * selected by an administrator, it is agreed to by every person expected in it,
 * from their own session. A space-picker-shaped control on this card would be
 * the exact affordance md/03 §3.1 refuses — an employer's answer standing in for
 * an employee's. What sits in `children` instead is a status word, read-only.
 */
function googleMeetCardProps({
  integration,
  connected,
  oauthReturn,
  connecting,
  install,
  onConnect,
  onDisconnect,
}: {
  integration: Integration | null;
  connected: boolean;
  oauthReturn: OAuthReturn | undefined;
  connecting: boolean;
  install: GoogleMeetInstall | null;
  onConnect: () => void;
  onDisconnect: () => void;
}): {
  requestedScopes: typeof GOOGLE_MEET_SCOPES;
  refusals: string[];
  disconnectEffect: string;
  connectedSummary: string;
  notice: ReactNode;
  onConnect: () => void;
  connecting: boolean;
  onDisconnect: () => void;
  oauthReturn?: OAuthReturn;
  children?: ReactNode;
} {
  // Only for a connection that exists. `googleMeetStatus(null)` is "not
  // connected", which the card's own state row and `stateDetail` already say —
  // and two state words on one card is a card the reader has to reconcile.
  const status = integration === null ? null : googleMeetStatus(integration);
  const expiresAt = googleMeetExpiry(integration);

  return {
    requestedScopes: GOOGLE_MEET_SCOPES,
    refusals: GOOGLE_MEET_REFUSALS,
    disconnectEffect: GOOGLE_MEET_DISCONNECT_EFFECT,
    // Replaces the card's default, which promises reading this connector never
    // does — see `ConnectionCardProps.connectedSummary`.
    connectedSummary: GOOGLE_MEET_CONNECTED_DETAIL,
    notice: googleMeetNotice(install, connected),
    onConnect,
    connecting,
    onDisconnect,
    ...(oauthReturn === undefined ? {} : { oauthReturn }),
    // Omitted entirely when the server sent no state to read. An absent status
    // is "CAIRN cannot say", and the card refuses to draw a placeholder that
    // would read as "fine".
    ...(status === null
      ? {}
      : {
          children: (
            <GoogleMeetStatusNote
              status={status}
              {...(expiresAt === undefined ? {} : { expiresAt })}
            />
          ),
        }),
  };
}

/**
 * What to read before authorising Google Meet.
 *
 * **The boundary sentence is first, always.** Not the unavailability, not the
 * link expiry, not the server's own notice: the thing a reader has to have read
 * before they press anything is that CAIRN does not join calls and does not
 * start recordings. Everything else on this card is a detail of a system whose
 * shape they will otherwise have got wrong.
 *
 * The unavailability follows, and only while Meet is not connected — a card
 * describing a live connection must not also carry a sentence saying that
 * connection is impossible.
 */
function googleMeetNotice(install: GoogleMeetInstall | null, connected: boolean): ReactNode {
  return (
    <>
      <strong>{GOOGLE_MEET_BOUNDARY}</strong> {GOOGLE_MEET_TRANSCRIPT_PERMISSION}
      {connected ? null : <> {GOOGLE_MEET_NOT_LIVE}</>}
      {install === null ? null : (
        <>
          {" "}
          {install.notice} Sending you to Google now. This link stops working at{" "}
          <time dateTime={install.expiresAt}>{formatDayAndTime(install.expiresAt)}</time> — if
          nothing happens, or you come back to this later, start again.
        </>
      )}
    </>
  );
}

/**
 * The space selection, saved one space at a time.
 *
 * The same rule as the channel picker's, and for the same reason: nothing is
 * written optimistically, so a refused save leaves the checkbox exactly where it
 * was and puts the reason beside it. `PUT` answers with resource names, and
 * `reconcileSpaces` is the one place that folds those back onto the list — the
 * tick still comes from what the server said, not from what was clicked.
 */
function GoogleChatSpaces({
  workspaceId,
  canManage,
}: {
  workspaceId: string;
  canManage: boolean;
}): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<GoogleChatSpaceList> =>
      client.listGoogleChatSpaces(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the Google Chat spaces");

  const [saved, setSaved] = useState<GoogleChatSpaceList | null>(null);
  const [saving, setSaving] = useState<string[]>([]);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  if (state.status === "loading") return <SpacePickerLoading />;
  if (state.status === "failed") {
    // A 403 arrives here with its own copy — "this account does not have access
    // to that" — so a permission refusal is answered rather than reported as a
    // generic failure.
    return (
      <ErrorState
        title="The Google Chat spaces could not be loaded"
        error={state.error}
        onRetry={reload}
        headingLevel={4}
      />
    );
  }

  const spaces = saved ?? state.data;

  async function toggle(spaceName: string, next: boolean): Promise<void> {
    // The whole state of the checkboxes, never a delta: `PUT` replaces rather
    // than merges, so an unchecked box has to arrive as an absence, and an
    // absence is only meaningful when everything else is present.
    const names = (spaces.spaces ?? [])
      .filter((space) => (space.name === spaceName ? next : space.selected))
      .map((space) => space.name);

    setSaving((busy) => [...busy, spaceName]);
    setProblem(null);
    try {
      const confirmed = await client.setGoogleChatSpaces(workspaceId, names);
      setSaved(reconcileSpaces(spaces, confirmed));
    } catch (error: unknown) {
      setProblem(describeError(error, "save that space choice"));
    } finally {
      setSaving((busy) => busy.filter((name) => name !== spaceName));
    }
  }

  return (
    <SpacePicker
      spaces={spaces}
      canManage={canManage}
      saving={saving}
      {...(problem === null ? {} : { problem })}
      onToggle={(spaceName, next) => {
        void toggle(spaceName, next);
      }}
    />
  );
}

/**
 * The channel selection, saved one channel at a time.
 *
 * **State comes back from the server, never from the click.** Nothing writes to
 * the selection optimistically, so a refused save leaves the checkbox exactly
 * where it was and puts the reason beside it. That costs a round trip of latency
 * per channel and buys the one property this screen cannot do without: a tick
 * means CAIRN is reading that room.
 *
 * The save answers with `channelIds` and no names, so `reconcileChannels` folds
 * that confirmation back onto the channels the `GET` described. The tick still
 * comes from what the server said, not from what was clicked.
 */
function SlackChannels({
  workspaceId,
  canManage,
}: {
  workspaceId: string;
  canManage: boolean;
}): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<SlackChannelList> =>
      client.listSlackChannels(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the Slack channels");

  const [saved, setSaved] = useState<SlackChannelList | null>(null);
  const [saving, setSaving] = useState<string[]>([]);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  if (state.status === "loading") return <ChannelPickerLoading />;
  if (state.status === "failed") {
    // A 403 arrives here with its own copy — "this account does not have access
    // to that" — so a permission refusal is answered rather than reported as a
    // generic failure.
    return (
      <ErrorState
        title="The Slack channels could not be loaded"
        error={state.error}
        onRetry={reload}
        headingLevel={4}
      />
    );
  }

  const selection = saved ?? state.data;

  async function toggle(channelId: string, next: boolean): Promise<void> {
    // The whole state of the checkboxes, never a delta: `PUT` replaces rather
    // than merges, so an unchecked box has to arrive as an absence, and an
    // absence is only meaningful when everything else is present.
    const ids = (selection.channels ?? [])
      .filter((channel) => (channel.id === channelId ? next : channel.selected))
      .map((channel) => channel.id);

    setSaving((busy) => [...busy, channelId]);
    setProblem(null);
    try {
      const confirmed = await client.setSlackChannels(workspaceId, ids);
      setSaved(reconcileChannels(selection, confirmed));
    } catch (error: unknown) {
      setProblem(describeError(error, "save that channel choice"));
    } finally {
      setSaving((busy) => busy.filter((id) => id !== channelId));
    }
  }

  return (
    <ChannelPicker
      selection={selection}
      canManage={canManage}
      saving={saving}
      {...(problem === null ? {} : { problem })}
      onToggle={(channelId, next) => {
        void toggle(channelId, next);
      }}
    />
  );
}
