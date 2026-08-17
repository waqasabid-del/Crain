"use client";

import type {
  Integration,
  Member,
  Notifications,
  Privacy,
  SlackChannelList,
  SlackInstall,
} from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useSearchParams } from "next/navigation";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth, type TenantRole } from "../auth/context.js";
import {
  ChannelPicker,
  ChannelPickerLoading,
  reconcileChannels,
} from "../components/ChannelPicker.js";
import {
  ConnectionCard,
  connectionRows,
  ConnectionsLoading,
  SLACK_DISCONNECT_EFFECT,
  SLACK_INVITE_RULE,
  SLACK_REFUSALS,
  SLACK_SCOPES,
  type OAuthReturn,
} from "../components/ConnectionCard.js";
import { formatDayAndTime } from "../components/dates.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { PageHeader } from "../components/PageHeader.js";
import { Section } from "../components/Section.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { StatusNote } from "../components/StatusNote.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./AdminPage.module.css";

/**
 * Running the workspace.
 *
 * Step 25's criterion is that an Owner can do it *without contacting support*,
 * which is a support-cost target with a security consequence attached: every
 * task an administrator cannot do is a task a member of CAIRN's staff does for
 * them, in their data, on their word.
 *
 * **Roles here decide what somebody may configure and never what they may see.**
 * There is no activity column on the member list, no "last active", no
 * engagement figure — and this screen is exactly where the first one would be
 * added, because every other product's admin area has one (md/15 §2.2).
 *
 * **What is offered is decided by role; what is allowed is decided by the API.**
 * Hiding a control the server would refuse is courtesy. Relying on that hiding
 * would be the bug, so nothing here is the only thing standing between a Viewer
 * and a role change.
 */

const ROLES: { value: TenantRole; label: string; detail: string }[] = [
  {
    value: "owner",
    label: "Owner",
    detail: "Everything, including billing and ending the workspace",
  },
  { value: "admin", label: "Admin", detail: "Runs the workspace day to day. No billing" },
  { value: "member", label: "Member", detail: "Reads everything, corrects their own record" },
  { value: "viewer", label: "Viewer", detail: "Reads everything. Changes nothing" },
];

/** Whether this role may change the workspace's configuration. */
function administers(role: TenantRole | null): boolean {
  return role === "owner" || role === "admin";
}

export function AdminPage(): ReactNode {
  const { activeWorkspace, activeRole } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Workspace" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is nothing to administer.
        </EmptyState>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Workspace"
        description="Who is here, what CAIRN is connected to, and what happens to what it records."
      />

      <Members workspaceId={activeWorkspace.id} role={activeRole} />
      <Integrations workspaceId={activeWorkspace.id} role={activeRole} />
      <PrivacySection workspaceId={activeWorkspace.id} role={activeRole} />
      {administers(activeRole) && <NotificationSection workspaceId={activeWorkspace.id} />}
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
// Members
// --------------------------------------------------------------------------

function Members({
  workspaceId,
  role,
}: {
  workspaceId: string;
  role: TenantRole | null;
}): ReactNode {
  const client = useApiClient();
  const { session } = useAuth();
  const load = useCallback(
    (signal: AbortSignal): Promise<Member[]> => client.listMembers(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the members");
  const [problem, setProblem] = useState<DescribedError | null>(null);

  return (
    <AdminSection
      title="Members"
      description="A role decides what somebody can configure. It never decides how much CAIRN shows them about a colleague — everyone sees the same thing."
    >
      {state.status === "loading" && <LoadingState label="the members" lines={3} />}
      {state.status === "failed" && (
        <ErrorState title="The members could not be loaded" error={state.error} onRetry={reload} />
      )}

      {problem !== null && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}

      {state.status === "ready" && (
        <ul className={styles.people} aria-label="Members">
          {state.data.map((member) => (
            <MemberRow
              key={member.userId}
              member={member}
              workspaceId={workspaceId}
              // The reader's own row offers no controls: the API refuses a
              // self-role-change, and offering a control that always fails is
              // worse than not offering it.
              isSelf={member.userId === session?.user.id}
              canAdminister={administers(role)}
              onChanged={reload}
              onProblem={setProblem}
            />
          ))}
        </ul>
      )}
    </AdminSection>
  );
}

function MemberRow({
  member,
  workspaceId,
  isSelf,
  canAdminister,
  onChanged,
  onProblem,
}: {
  member: Member;
  workspaceId: string;
  isSelf: boolean;
  canAdminister: boolean;
  onChanged: () => void;
  onProblem: (problem: DescribedError | null) => void;
}): ReactNode {
  const client = useApiClient();
  const roleId = useId();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function change(next: string): Promise<void> {
    setBusy(true);
    onProblem(null);
    try {
      await client.changeRole(workspaceId, member.userId, next);
      onChanged();
    } catch (error: unknown) {
      onProblem(describeError(error, "change that role"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(): Promise<void> {
    setBusy(true);
    onProblem(null);
    try {
      await client.removeMember(workspaceId, member.userId);
      onChanged();
    } catch (error: unknown) {
      onProblem(describeError(error, "remove that person"));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <li className={styles.person}>
      <div>
        <div className={styles.personName}>{member.displayName ?? member.email}</div>
        {/*
          The address is the second line only when it is not already the first.
          Somebody who has not set a name would otherwise be listed as their own
          email twice, which reads as a rendering fault rather than as a person
          who has not filled in a field.
        */}
        {member.displayName != null && <div className={styles.personDetail}>{member.email}</div>}
      </div>

      {canAdminister && !isSelf ? (
        <div className={styles.personControls}>
          <label className={utility.visuallyHidden} htmlFor={roleId}>
            Role for {member.displayName ?? member.email}
          </label>
          <select
            id={roleId}
            className={styles.select}
            value={member.role}
            disabled={busy}
            onChange={(event) => {
              void change(event.target.value);
            }}
          >
            {ROLES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          {/*
            Two steps, and the second one says what it does rather than "Are you
            sure?". A confirmation that restates the consequence is one somebody
            can actually decline; a generic one is a button people learn to click
            without reading.
          */}
          {confirming ? (
            <>
              <Button
                size="sm"
                variant="secondary"
                loading={busy}
                onClick={() => {
                  void remove();
                }}
              >
                Remove their access
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setConfirming(false);
                }}
              >
                Keep them
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setConfirming(true);
              }}
            >
              Remove
            </Button>
          )}
        </div>
      ) : (
        <span className={styles.roleLabel}>{roleLabel(member.role)}</span>
      )}

      {confirming && (
        <p className={styles.note}>
          They lose access to this workspace. What CAIRN already recorded about their work stays —
          it is the team&rsquo;s history, not only theirs.
        </p>
      )}
    </li>
  );
}

function roleLabel(role: string): string {
  return ROLES.find((option) => option.value === role)?.label ?? role;
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
  const [problem, setProblem] = useState<{ id: string; error: DescribedError } | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const oauthReturn = readOAuthReturn(useSearchParams().get("slack"));
  const [connecting, setConnecting] = useState(false);
  const [install, setInstall] = useState<SlackInstall | null>(null);

  const canManage = administers(role);

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
    setConnecting(true);
    setProblem(null);
    try {
      const started = await client.startSlackInstall(workspaceId);
      setInstall(started);
      window.location.assign(started.authorizeUrl);
    } catch (error: unknown) {
      setProblem({ id, error: describeError(error, "start connecting Slack") });
    } finally {
      setConnecting(false);
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
              const isSlack = row.source === "slack";
              const connected = connection.state === "connected";

              return (
                <li key={connection.id}>
                  <ConnectionCard
                    connection={connection}
                    canManage={canManage}
                    disconnecting={busyId === connection.id}
                    {...(failure === undefined ? {} : { problem: failure })}
                    {...(isSlack
                      ? slackCardProps({
                          workspaceId,
                          connected,
                          oauthReturn,
                          canManage,
                          connecting,
                          install,
                          onConnect: () => {
                            void connectSlack(connection.id);
                          },
                          onDisconnect: () => {
                            void disconnectSlack(connection.id);
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

// --------------------------------------------------------------------------
// Privacy and data
// --------------------------------------------------------------------------

function PrivacySection({
  workspaceId,
  role,
}: {
  workspaceId: string;
  role: TenantRole | null;
}): ReactNode {
  const client = useApiClient();
  const fieldId = useId();
  const load = useCallback(
    (signal: AbortSignal): Promise<Privacy> => client.getPrivacy(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the privacy settings");

  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const current = state.status === "ready" ? state.data : null;
  const value = draft ?? (current === null ? "" : String(current.retentionDays));

  async function save(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    setSaved(null);
    try {
      const updated = await client.setRetention(workspaceId, Number(value));
      setDraft(null);
      setSaved(
        `Raw activity is now kept for ${String(updated.retentionDays)} days. Anything older than that is deleted on the next sweep.`,
      );
      reload();
    } catch (error: unknown) {
      setProblem(describeError(error, "change the retention period"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminSection
      title="Privacy and data"
      description="How long CAIRN keeps the raw activity it received — the messages and payloads themselves. What CAIRN understood from them, and the briefs written from that, stay: they are the team's record."
    >
      {state.status === "loading" && <LoadingState label="the settings" lines={2} />}
      {state.status === "failed" && (
        <ErrorState title="The settings could not be loaded" error={state.error} onRetry={reload} />
      )}

      {current !== null && (
        <>
          <form
            className={styles.retention}
            onSubmit={(event) => {
              void save(event);
            }}
          >
            <div className={styles.control}>
              <label className={styles.label} htmlFor={fieldId}>
                Keep raw activity for
              </label>
              <div className={styles.retentionRow}>
                <input
                  id={fieldId}
                  className={styles.number}
                  type="number"
                  inputMode="numeric"
                  min={current.minRetentionDays}
                  max={current.maxRetentionDays}
                  value={value}
                  disabled={!administers(role) || busy}
                  onChange={(event) => {
                    setDraft(event.target.value);
                  }}
                />
                <span className={styles.unit}>days</span>
                {administers(role) && (
                  <Button type="submit" loading={busy}>
                    Save
                  </Button>
                )}
              </div>
              <p className={styles.hint}>
                Between {current.minRetentionDays} and {current.maxRetentionDays} days. Shortening
                this deletes what has just fallen outside the window, and that cannot be undone.
              </p>
            </div>
          </form>

          {saved !== null && (
            <div className={styles.note}>
              <StatusNote>{saved}</StatusNote>
            </div>
          )}
          {problem !== null && (
            <div className={styles.problem}>
              <InlineProblem error={problem} />
            </div>
          )}

          <dl className={styles.facts}>
            <dt>Stored in</dt>
            <dd>
              {current.region}
              {/*
                Shown and not editable. Moving a workspace between regions is a
                data migration under compliance pressure, and a dropdown that
                silently did nothing would be worse than its absence.
              */}
              <span className={styles.personDetail}> — changing this is not self-service yet.</span>
            </dd>
          </dl>
        </>
      )}
    </AdminSection>
  );
}

// --------------------------------------------------------------------------
// Worker notification
// --------------------------------------------------------------------------

/**
 * Who has been told, and how many have opted out.
 *
 * **Named on one side, counted on the other**, which is the most considered
 * decision on this screen. Notification is an obligation owed to each person
 * before capture begins, so an administrator has to be able to see who is
 * outstanding. An opt-out is that person's own decision about their own record,
 * and a list of names beside "opted out" is a list of employees who declined to
 * be recorded, handed to whoever writes their review.
 *
 * The number is what md/11 §7 makes the product's trust barometer and md/13
 * makes a phase gate — and a rate is what a gate needs. A list is not.
 */
function NotificationSection({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Notifications> =>
      client.getNotifications(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the notification status");

  if (state.status === "loading") return <LoadingState label="the notification status" lines={2} />;
  if (state.status === "failed") {
    return (
      <AdminSection title="Worker notification">
        <ErrorState title="The status could not be loaded" error={state.error} onRetry={reload} />
      </AdminSection>
    );
  }

  const people = state.data.people ?? [];
  const outstanding = people.filter((person) => person.notifiedAt == null);

  return (
    <AdminSection
      title="Worker notification"
      description="CAIRN attributes nothing to a person until it has shown them what it reads and how to switch it off. This is who has seen that."
    >
      {outstanding.length === 0 ? (
        <p className={styles.note}>
          Everyone here has been shown it. Nothing is attributed to somebody who has not.
        </p>
      ) : (
        <p className={styles.note}>
          {outstanding.length} of {people.length}{" "}
          {outstanding.length === 1 ? "person has" : "people have"} not seen it yet. Their work is
          still recorded as the team&rsquo;s, with their name in the text — but CAIRN does not
          attribute it to them until they have.
        </p>
      )}

      <ul className={styles.people} aria-label="Worker notification">
        {people.map((person) => (
          <li key={person.userId} className={styles.person}>
            <div>
              <div className={styles.personName}>{person.displayName ?? person.email}</div>
              <div className={styles.personDetail}>
                {person.notifiedAt == null
                  ? "Not shown yet"
                  : `Shown on ${new Date(person.notifiedAt).toLocaleDateString()}`}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {/*
        A number, never a list. See this section's docstring: the names would
        turn a privacy control into a career calculation, and the resulting low
        number would mean nothing.
      */}
      <p className={styles.note}>
        {state.data.optedOutCount === 0
          ? "Nobody has switched off a source."
          : `${String(state.data.optedOutCount)} ${state.data.optedOutCount === 1 ? "person has" : "people have"} switched off at least one source. CAIRN does not say who — that is their decision about their own record.`}
      </p>
    </AdminSection>
  );
}
