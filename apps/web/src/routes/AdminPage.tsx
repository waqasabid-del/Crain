"use client";

import type { Integration, Member, Notifications, Privacy } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth, type TenantRole } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
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

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}): ReactNode {
  const headingId = useId();
  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <h2 className={styles.sectionTitle} id={headingId}>
        {title}
      </h2>
      {description !== undefined && <p className={styles.sectionBody}>{description}</p>}
      {children}
    </section>
  );
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
    <Section
      title="Members"
      description="A role decides what somebody can configure. It never decides how much CAIRN shows them about a colleague — everyone sees the same thing."
    >
      {state.status === "loading" && <LoadingState label="the members" lines={3} />}
      {state.status === "failed" && (
        <ErrorState title="The members could not be loaded" error={state.error} onRetry={reload} />
      )}

      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
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
    </Section>
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
          <label className={styles.visuallyHidden} htmlFor={roleId}>
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
  const { state, reload } = useAsync(load, "load the integrations");
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [busy, setBusy] = useState(false);

  async function disconnect(installationId: number): Promise<void> {
    setBusy(true);
    setProblem(null);
    try {
      await client.disconnectGitHub(workspaceId, installationId);
      reload();
    } catch (error: unknown) {
      setProblem(describeError(error, "disconnect that integration"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      title="Connected sources"
      description="What CAIRN is reading. Disconnecting stops it reading anything more — it does not remove what has already been recorded."
    >
      {state.status === "loading" && <LoadingState label="the integrations" lines={2} />}
      {state.status === "failed" && (
        <ErrorState
          title="The integrations could not be loaded"
          error={state.error}
          onRetry={reload}
        />
      )}

      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}

      {state.status === "ready" &&
        (state.data.length === 0 ? (
          <EmptyState title="Nothing connected yet">
            CAIRN captures nothing until a source is connected. Connecting GitHub is what starts it.
          </EmptyState>
        ) : (
          <ul className={styles.integrations} aria-label="Connected sources">
            {state.data.map((integration) => (
              <li key={`${integration.source}-${integration.account}`} className={styles.person}>
                <div>
                  <div className={styles.personName}>GitHub — {integration.account}</div>
                  <div className={styles.personDetail}>
                    {integration.disconnectedAt != null
                      ? "Disconnected. CAIRN is no longer reading from this account."
                      : integration.suspended
                        ? "Suspended on GitHub. Nothing is being read while it stays that way."
                        : "Reading commit messages, pull request titles and reviews. Never the contents of your code."}
                  </div>
                </div>

                {administers(role) && integration.disconnectedAt == null && (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy}
                    onClick={() => {
                      void disconnect(integration.installationId);
                    }}
                  >
                    Disconnect
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ))}
    </Section>
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
    <Section
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
            <p className={styles.note} role="status">
              {saved}
            </p>
          )}
          {problem !== null && (
            <p className={styles.problem} role="alert">
              {problem.message}
            </p>
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
    </Section>
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
      <Section title="Worker notification">
        <ErrorState title="The status could not be loaded" error={state.error} onRetry={reload} />
      </Section>
    );
  }

  const people = state.data.people ?? [];
  const outstanding = people.filter((person) => person.notifiedAt == null);

  return (
    <Section
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
    </Section>
  );
}
