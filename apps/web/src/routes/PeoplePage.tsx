"use client";

import type { Invitation, Member } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Avatar } from "../components/Avatar.js";
import { CapacityChip } from "../components/CapacityChip.js";
import { Card } from "../components/Card.js";
import { Field } from "../components/Field.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { PageHeader } from "../components/PageHeader.js";
import { StatusNote } from "../components/StatusNote.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync, type AsyncState } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./PeoplePage.module.css";

/**
 * The team — md/15 §4.2 screen 18.
 *
 * A card each, and every card opens that person's page. The cards carry
 * identity, the workspace role, and the person's own words about their
 * availability. **They carry nothing that measures anybody**: no count, no
 * volume, no "last active", no ordering that could be read as importance. A
 * members list is where comparative measurement first appears in a product,
 * and this one is built so there is nowhere for it to go (md/05 §B.3.3).
 *
 * Owners and Admins can invite from here. The invitation is an email to an
 * address; the token that redeems it never returns to this screen, because
 * issuing an invitation and proving control of the address are two different
 * things and the API keeps them apart.
 */
export function PeoplePage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Team" description="Everyone in this workspace." />
        <EmptyState
          title="Join a workspace to see the team"
          action={
            <Link className={utility.actionLink} href="/settings">
              Check which account you are using
            </Link>
          }
        >
          An invitation from a colleague adds you to theirs.
        </EmptyState>
      </>
    );
  }

  return <WorkspaceMembers workspaceId={activeWorkspace.id} />;
}

/**
 * How many projects are examined to collect people's job roles.
 *
 * BACKEND GAP: there is no endpoint that returns a person's project
 * memberships, so the roles shown on these cards are collected by reading the
 * portfolio and then each project. Bounded, because the cost is one request
 * per project. When an endpoint lands, this fan-out and its cap go with it.
 */
const PROJECTS_EXAMINED = 20;

/**
 * The two workspace roles worth showing, and why the other two are not.
 *
 * "Owner" and "Admin" say who can configure the workspace, which is genuinely
 * useful to know before you ask somebody for something. "Member" and "Viewer"
 * say nothing a colleague needs — they are permission plumbing, and printing
 * them on a person's card labels people by their access level. What belongs
 * there is the work they do, which is their project roles below.
 */
const PERMISSION_LABEL: Readonly<Record<string, string>> = {
  owner: "Owner",
  admin: "Admin",
};

interface Roster {
  members: Member[];
  /** person id -> the job roles they hold, in the order projects were read. */
  rolesByPerson: Map<string, string[]>;
}

function WorkspaceMembers({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const { activeRole } = useAuth();
  const load = useCallback(
    async (signal: AbortSignal): Promise<Roster> => {
      const options = { signal };
      const [members, portfolio] = await Promise.all([
        client.listMembers(workspaceId, options),
        client.listProjects(workspaceId, undefined, options),
      ]);

      const projects = (portfolio.projects ?? []).slice(0, PROJECTS_EXAMINED);
      const details = await Promise.all(
        projects.map((project) => client.getProject(workspaceId, project.id, options)),
      );

      const rolesByPerson = new Map<string, string[]>();
      for (const detail of details) {
        for (const membership of detail.members ?? []) {
          // A closed membership is history: the role is no longer held.
          if (membership.removedAt != null) continue;
          const role = membership.projectRole;
          if (role == null || role.trim() === "") continue;
          const held = rolesByPerson.get(membership.personId) ?? [];
          if (!held.includes(role)) held.push(role);
          rolesByPerson.set(membership.personId, held);
        }
      }

      return { members, rolesByPerson };
    },
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the people in this workspace");

  // Decides what to *offer*, never what to allow — the API enforces the
  // permission and will refuse a request this screen was wrong to show.
  const canInvite = activeRole === "owner" || activeRole === "admin";

  return (
    <>
      <PageHeader
        title="Team"
        description="Everyone in this workspace, and what they work on."
        meta={state.status === "ready" ? membersLabel(state.data.members.length) : undefined}
        actions={
          <Link className={utility.actionLink} href="/trust">
            Trust Center
          </Link>
        }
      />

      {canInvite && <InvitationArea workspaceId={workspaceId} onInvited={reload} />}

      {state.status === "loading" && (
        <LoadingState label="the people in this workspace" shape="rows" lines={4} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="The team could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/trust">
              Who can see what
            </Link>
          }
        />
      )}

      {state.status === "ready" &&
        (state.data.members.length === 0 ? (
          <EmptyState
            title="Nobody here yet"
            action={
              <Link className={utility.actionLink} href="/settings">
                Workspace settings
              </Link>
            }
          >
            Colleagues appear here once they accept an invitation.
          </EmptyState>
        ) : (
          <>
            {/* A list, not a table: each person is a card that opens their
              page, and a grid of links reads better to both eyes and screen
              readers than a table whose every row has one actionable cell. */}
            <ul className={styles.grid} aria-label="People in this workspace">
              {state.data.members.map((member) => (
                <li key={member.userId}>
                  <MemberCard
                    member={member}
                    roles={
                      member.personId == null
                        ? []
                        : (state.data.rolesByPerson.get(member.personId) ?? [])
                    }
                  />
                </li>
              ))}
            </ul>
          </>
        ))}
    </>
  );
}

/**
 * One person, as a card that opens their page.
 *
 * The whole card is not the link; the name is. A card-wide target would
 * swallow the capacity chip and make the accessible name of the link the
 * entire card's text, which is how a screen reader ends up announcing a
 * paragraph where a name belongs.
 */
function MemberCard({ member, roles }: { member: Member; roles: string[] }): ReactNode {
  const name = member.displayName ?? member.email;
  const personId = member.personId ?? null;
  const permission = PERMISSION_LABEL[member.role];

  return (
    <article className={styles.card}>
      <Avatar name={name} size="md" />
      <div className={styles.cardBody}>
        <h2 className={styles.cardName}>
          {personId === null ? (
            name
          ) : (
            <Link className={styles.cardLink} href={`/people/${personId}`}>
              {name}
            </Link>
          )}
        </h2>
        {roles.length === 0 ? (
          <p className={styles.cardRole}>No role set</p>
        ) : (
          <ul className={styles.roles}>
            {roles.map((role) => (
              <li className={styles.rolePill} key={role}>
                {role}
              </li>
            ))}
          </ul>
        )}
        <p className={styles.cardEmail}>{member.email}</p>
        <div className={styles.cardFoot}>
          <CapacityChip capacity={member.capacity} />
          {permission !== undefined && <span className={styles.permission}>{permission}</span>}
        </div>
      </div>
    </article>
  );
}

/**
 * The three roles an invitation can grant, said as what they let somebody do.
 *
 * The wire values are `member`, `admin` and `viewer` and stay exactly that;
 * only the label changes. A bare "Viewer" in a dropdown asks the reader to
 * guess, and the guess is usually wrong in the generous direction — which is
 * the wrong direction for a permission.
 *
 * These are *permission* levels, not job titles. What somebody does — Frontend,
 * Backend, DevOps, UI/UX Design — is set per project when they are added to
 * one, which is why the form says so: an admin who came here looking for
 * "Frontend" should leave knowing where it actually lives rather than picking
 * the nearest-sounding permission.
 */
const ROLE_CHOICES = [
  { value: "member", label: "Member — can read everything and correct their own record" },
  { value: "admin", label: "Admin — can also change workspace settings and invite people" },
  { value: "viewer", label: "Viewer — read only" },
] as const;

type InvitableRole = (typeof ROLE_CHOICES)[number]["value"];

/** The same words on a pending row as in the dropdown that produced it, plus
 * Owner, which no invitation issues here but which the API's role type allows
 * and this screen should not render as a blank. */
const ROLE_MEANING: Readonly<Record<string, string>> = {
  member: "Member — can read everything and correct their own record",
  admin: "Admin — can also change workspace settings and invite people",
  viewer: "Viewer — read only",
  owner: "Owner — can change anything in this workspace",
};

function roleMeaning(role: string): string {
  return ROLE_MEANING[role] ?? "Access is set by the workspace";
}

/** The options the select renders are the only values it can produce; this
 * keeps that true by checking rather than by asserting it. */
function isInvitableRole(value: string): value is InvitableRole {
  return ROLE_CHOICES.some((choice) => choice.value === value);
}

const MS_PER_DAY = 86_400_000;

/**
 * When an invitation runs out, in whole days, exactly.
 *
 * Pure and calendar-based on purpose. "Expires today" means the expiry falls on
 * today's date, not "some time in the next 24 hours", so the words on screen
 * and the date the reader would see in their own calendar agree. The vague
 * middle ground — "expires soon" — is the one wording this must never use: an
 * admin deciding whether to re-invite somebody needs to know whether the link
 * in that person's inbox still works.
 *
 * An unparseable timestamp says so rather than rendering "Invalid Date" or,
 * worse, silently reading as "Expired".
 */
function expiryLabel(expiresAt: string, now: Date): string {
  const expiry = new Date(expiresAt);
  const at = expiry.getTime();
  if (Number.isNaN(at)) return "Expiry unknown";
  if (at <= now.getTime()) return "Expired";

  const days = calendarDaysBetween(now, expiry);
  if (days <= 0) return "Expires today";
  if (days === 1) return "Expires tomorrow";
  return `Expires in ${String(days)} days`;
}

/** Whole days between two calendar dates, local time. `Date.UTC` on the
 * already-local parts sidesteps daylight saving, where a plain millisecond
 * division is off by one twice a year. */
function calendarDaysBetween(from: Date, to: Date): number {
  const a = Date.UTC(from.getFullYear(), from.getMonth(), from.getDate());
  const b = Date.UTC(to.getFullYear(), to.getMonth(), to.getDate());
  return Math.round((b - a) / MS_PER_DAY);
}

/**
 * Issuing invitations, and the invitations already issued.
 *
 * The two live together because they are one question — "who is joining?" — and
 * because sending one has to change the other. The list of outstanding
 * invitations is read here rather than inside the form so that a successful
 * send can refresh both this list and the member list without either of them
 * knowing about the other.
 */
function InvitationArea({
  workspaceId,
  onInvited,
}: {
  workspaceId: string;
  onInvited: () => void;
}): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Invitation[]> => client.listInvitations(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the pending invitations");

  return (
    <>
      <InvitePanel
        workspaceId={workspaceId}
        onInvited={() => {
          // Both reads: the member list because an admin who just invited
          // somebody expects the screen to have re-read itself, and this list
          // because the invitation they just sent belongs in it now.
          onInvited();
          reload();
        }}
      />
      <PendingInvitations
        workspaceId={workspaceId}
        state={state}
        onWithdrawn={reload}
        onRetry={reload}
      />
    </>
  );
}

/**
 * Invite a colleague by email.
 *
 * A disclosure rather than a dialog: the panel takes the flow and pushes the
 * list down instead of covering it, so there is no overlay to trap focus
 * inside and no background scroll to lock — the four obligations that make
 * modals go subtly wrong, for a form with two fields.
 *
 * The confirmation says the address and nothing else. There is no link to copy
 * here on purpose: the token reaches the invitee's inbox and nowhere else, so
 * that issuing an invitation and proving control of the address stay separate.
 */
function InvitePanel({
  workspaceId,
  onInvited,
}: {
  workspaceId: string;
  onInvited: () => void;
}): ReactNode {
  const client = useApiClient();
  const panelId = useId();
  const roleId = useId();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<InvitableRole>("member");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  async function submit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setProblem(null);
    setSent(null);
    setSending(true);
    try {
      const invitation = await client.invite(workspaceId, { email, role });
      setSent(invitation.email);
      setEmail("");
      // The member list does not change until they accept, but an admin who
      // just invited somebody expects the screen to have re-read itself.
      onInvited();
    } catch (error: unknown) {
      setProblem(describeError(error, "send this invitation"));
    } finally {
      setSending(false);
    }
  }

  return (
    <Card className={styles.invite}>
      <div className={styles.inviteHead}>
        <div>
          <h2 className={styles.inviteTitle}>Invite a colleague</h2>
          <p className={styles.inviteNote}>They receive a link by email to join this workspace.</p>
        </div>
        <Button
          type="button"
          variant={open ? "secondary" : "primary"}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setOpen(!open);
          }}
        >
          {open ? "Cancel" : "Invite member"}
        </Button>
      </div>

      {open && (
        <form className={styles.inviteForm} id={panelId} onSubmit={(event) => void submit(event)}>
          <Field
            label="Email address"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />

          {/* Hand-rolled rather than through `Field`, which owns an `<input>`:
            a role is a closed set, and a native select is the control that
            already works with every keyboard and screen reader. */}
          <div className={styles.roleField}>
            <label className={styles.roleLabel} htmlFor={roleId}>
              Role
            </label>
            <select
              id={roleId}
              className={styles.select}
              value={role}
              onChange={(event) => {
                // The options below are the only values this can produce, and
                // the guard keeps that true rather than asserting it.
                const chosen = event.target.value;
                if (isInvitableRole(chosen)) setRole(chosen);
              }}
            >
              {ROLE_CHOICES.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </select>
            {/* Said here because this is where an admin looks for it and does
              not find it. A permission is not a job title, and leaving the
              difference unsaid makes somebody pick the nearest-sounding
              permission instead of going to the project. */}
            <p className={styles.formHint}>
              This is what they may do, not what they work on. Job roles — Frontend, Backend,
              DevOps, UI/UX Design — are set on a project, when somebody is added to it.
            </p>
          </div>

          <Button type="submit" loading={sending}>
            Send invitation
          </Button>

          {/* There is no resend endpoint, deliberately: re-issuing means a new
            link and a new expiry, which is what inviting again already does. */}
          <p className={styles.formHint}>
            There is no resend button. To send a fresh link, invite the same address again.
          </p>

          {problem !== null && <InlineProblem error={problem} />}
        </form>
      )}

      {sent !== null && <StatusNote>Invitation sent to {sent}.</StatusNote>}
    </Card>
  );
}

/**
 * The invitations that have been sent and not yet accepted.
 *
 * Without this, "invite" was half a feature: an admin could issue an invitation
 * and then had no way to see it existed, tell it apart from a colleague who had
 * actually joined, or take it back. Each row says the address, what the
 * invitation would grant in plain words, and exactly when it runs out.
 *
 * Withdrawing is two clicks in place rather than a dialog. A row with an
 * address and a role does not justify an overlay, a focus trap, an inert
 * background and a dismissal path — four obligations that go subtly wrong far
 * more often than a mis-click on a reversible action does. The second click
 * happens where the first one did, so the address the reader is deciding about
 * never leaves the screen, and re-inviting undoes the mistake.
 *
 * The list never carries a count, an ordering or anything else that would
 * compare one person with another; it is a queue of outstanding letters.
 */
function PendingInvitations({
  workspaceId,
  state,
  onWithdrawn,
  onRetry,
}: {
  workspaceId: string;
  state: AsyncState<Invitation[]>;
  onWithdrawn: () => void;
  onRetry: () => void;
}): ReactNode {
  const client = useApiClient();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  // Read once per render rather than per row, so every row on screen is
  // measured against the same instant.
  const now = new Date();

  function withdraw(invitationId: string): void {
    setBusy(invitationId);
    setProblem(null);

    client
      .withdrawInvitation(workspaceId, invitationId)
      .then(() => {
        // Only now: nothing is removed from the list optimistically, because a
        // refused withdrawal that had already erased the row would leave the
        // reader believing an invitation was gone while its link still works.
        setConfirming(null);
        onWithdrawn();
      })
      .catch((error: unknown) => {
        setProblem(describeError(error, "withdraw this invitation"));
      })
      .finally(() => {
        setBusy(null);
      });
  }

  return (
    <Card
      className={styles.pending}
      title="Pending invitations"
      description="Sent, and not accepted yet. Withdrawing stops the link in that person's inbox from working."
    >
      {state.status === "loading" && (
        <LoadingState label="the pending invitations" shape="rows" lines={2} />
      )}

      {/* Its own failure, in its own card: the team below is a separate read and
        stays on screen when this one cannot be loaded. */}
      {state.status === "failed" && (
        <ErrorState
          title="Pending invitations could not be loaded"
          error={state.error}
          onRetry={onRetry}
          headingLevel={3}
        />
      )}

      {state.status === "ready" &&
        (state.data.length === 0 ? (
          <EmptyState title="No pending invitations" headingLevel={3}>
            Everyone who has been invited has either joined or had their invitation withdrawn.
          </EmptyState>
        ) : (
          <>
            {problem !== null && (
              <div className={styles.pendingProblem}>
                <InlineProblem error={problem} />
              </div>
            )}
            <ul className={styles.pendingList} aria-label="Pending invitations">
              {state.data.map((invitation) => (
                <li className={styles.pendingRow} key={invitation.id}>
                  <div className={styles.pendingWho}>
                    <p className={styles.pendingEmail}>{invitation.email}</p>
                    <p className={styles.pendingRole}>{roleMeaning(invitation.role)}</p>
                  </div>
                  <time className={styles.pendingExpiry} dateTime={invitation.expiresAt}>
                    {expiryLabel(invitation.expiresAt, now)}
                  </time>
                  {confirming === invitation.id ? (
                    <span className={styles.pendingActions}>
                      <Button
                        size="sm"
                        variant="primary"
                        loading={busy === invitation.id}
                        aria-label={`Confirm withdrawing the invitation to ${invitation.email}`}
                        onClick={() => {
                          withdraw(invitation.id);
                        }}
                      >
                        Confirm
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy === invitation.id}
                        aria-label={`Keep the invitation to ${invitation.email}`}
                        onClick={() => {
                          setConfirming(null);
                        }}
                      >
                        Cancel
                      </Button>
                    </span>
                  ) : (
                    <span className={styles.pendingActions}>
                      <Button
                        size="sm"
                        disabled={busy !== null}
                        aria-label={`Withdraw the invitation to ${invitation.email}`}
                        onClick={() => {
                          setProblem(null);
                          setConfirming(invitation.id);
                        }}
                      >
                        Withdraw
                      </Button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </>
        ))}
    </Card>
  );
}

/** Singular when there is one of them: "1 members" is the sound of a machine. */
function membersLabel(count: number): string {
  return count === 1 ? "1 person" : `${String(count)} people`;
}
