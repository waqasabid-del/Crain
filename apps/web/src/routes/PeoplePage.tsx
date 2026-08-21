"use client";

import type { Member } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth, type TenantRole } from "../auth/context.js";
import { Avatar } from "../components/Avatar.js";
import { CapacityChip } from "../components/CapacityChip.js";
import { Card } from "../components/Card.js";
import { Field } from "../components/Field.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { PageHeader } from "../components/PageHeader.js";
import { StatusNote } from "../components/StatusNote.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
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

      {canInvite && <InvitePanel workspaceId={workspaceId} onInvited={reload} />}

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
  const [role, setRole] = useState<Exclude<TenantRole, "owner">>("member");
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
                if (chosen === "member" || chosen === "admin" || chosen === "viewer") {
                  setRole(chosen);
                }
              }}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>

          <Button type="submit" loading={sending}>
            Send invitation
          </Button>

          {problem !== null && <InlineProblem error={problem} />}
        </form>
      )}

      {sent !== null && <StatusNote>Invitation sent to {sent}.</StatusNote>}
    </Card>
  );
}

/** Singular when there is one of them: "1 members" is the sound of a machine. */
function membersLabel(count: number): string {
  return count === 1 ? "1 person" : `${String(count)} people`;
}
