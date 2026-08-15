"use client";

import type { Member } from "@cairn/api-client";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./PeoplePage.module.css";

/** Who is in this workspace — md/15 §4.2 screen 18, read-only for now. The list
 * carries no activity column: roles govern settings, never visibility. */
export function PeoplePage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="People" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is nobody to list.
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
        title="People"
        description="Everyone in this workspace, and what they can configure. Roles govern settings, never how much CAIRN shows about a person — everyone sees the same categories of information about everyone, including leadership."
        meta={state.status === "ready" ? `${String(state.data.length)} members` : undefined}
      />

      {state.status === "loading" && <LoadingState label="the people in this workspace" />}

      {state.status === "failed" && (
        <ErrorState
          title="The people list could not be loaded"
          error={state.error}
          onRetry={reload}
        />
      )}

      {state.status === "ready" &&
        (state.data.length === 0 ? (
          <EmptyState title="Nobody here yet">
            Once colleagues accept an invitation they appear here. An invited person joins this
            workspace rather than starting one of their own.
          </EmptyState>
        ) : (
          <MembersTable members={state.data} />
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

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
