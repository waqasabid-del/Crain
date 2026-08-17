"use client";

import type { Member } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { StatusNote } from "../components/StatusNote.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./PeoplePage.module.css";

/** Who is in this workspace — md/15 §4.2 screen 18, read-only for now. The list
 * carries no activity column: roles govern settings, never visibility. */
export function PeoplePage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader
          title="Team"
          description="Everyone in this workspace, and what each of them can configure."
        />
        <EmptyState
          title="Join a workspace to see the team"
          action={
            <Link className={utility.actionLink} href="/settings">
              Check which account you are using
            </Link>
          }
        >
          This account is not a member of a workspace yet, so there is nobody to list. An invitation
          from a colleague adds you to theirs.
        </EmptyState>
      </>
    );
  }

  return <WorkspaceMembers workspaceId={activeWorkspace.id} />;
}

function WorkspaceMembers({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Member[]> => client.listMembers(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the people in this workspace");

  return (
    <>
      <PageHeader
        title="Team"
        description="Everyone in this workspace, and what each of them can configure. A role governs settings, never how much CAIRN shows about a person — everyone sees the same categories of information about everyone, including about leadership."
        meta={state.status === "ready" ? membersLabel(state.data.length) : undefined}
        actions={
          <Link className={utility.actionLink} href="/trust">
            Trust Center
          </Link>
        }
      />

      {state.status === "loading" && (
        <LoadingState label="the people in this workspace" shape="table" lines={4} />
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
        (state.data.length === 0 ? (
          <EmptyState
            title="Nobody here yet"
            action={
              <Link className={utility.actionLink} href="/settings">
                Workspace settings
              </Link>
            }
          >
            Colleagues appear here once they accept an invitation. An invited person joins this
            workspace rather than starting one of their own.
          </EmptyState>
        ) : (
          <>
            <MembersTable members={state.data} />
            {/*
              Read-only, and said plainly rather than left to be discovered by a
              click that does nothing. `live={false}`: this is standing guidance
              on first paint, not the result of an action, and a live region
              that was never live is noise a screen-reader user cannot mute.
            */}
            <div className={styles.readOnly}>
              <StatusNote live={false}>
                This list is read-only here. Roles and invitations are changed in Workspace
                settings, by an admin.
              </StatusNote>
            </div>
          </>
        ))}
    </>
  );
}

function MembersTable({ members }: { members: Member[] }): ReactNode {
  return (
    <div className={styles.wrapper}>
      <table className={styles.table}>
        {/* The table's own name in a screen reader's table list. */}
        <caption className={styles.caption}>
          Members of this workspace and the settings each can change.
        </caption>
        <thead>
          <tr>
            {/* `scope="col"`, or the table is a grid of unlabelled cells. */}
            <th scope="col">Name</th>
            <th scope="col">Email</th>
            <th scope="col">Role</th>
            <th scope="col">Joined</th>
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.userId}>
              {/* `scope="row"` identifies the row, so a cell is announced as
                "Ali Rahman, Role, Admin" rather than "Admin". */}
              <th scope="row" className={styles.name}>
                {member.displayName ?? member.email}
              </th>
              <td className={styles.muted}>{member.email}</td>
              <td>
                <span className={styles.role}>{member.role}</span>
              </td>
              <td className={styles.muted}>
                {/* Machine-readable in `dateTime`, the reader's own locale in
                  the text. */}
                <time dateTime={member.joinedAt}>{formatDate(member.joinedAt)}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Singular when there is one of them: "1 members" is the sound of a machine. */
function membersLabel(count: number): string {
  return count === 1 ? "1 person" : `${String(count)} people`;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
