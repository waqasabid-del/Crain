"use client";

import type { Member } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import { Avatar } from "./Avatar.js";
import { CapacityChip } from "./CapacityChip.js";
import { Card } from "./Card.js";
import { EmptyState, ErrorState, LoadingState } from "./States.js";
import styles from "./TeamPanel.module.css";

/** Six rows, then the link. A panel is a way in to the team page, not a second
 * copy of it, and a full roster on the dashboard is a directory nobody asked
 * for. */
const SHOWN = 6;

/**
 * Who is in this workspace, as a dashboard panel.
 *
 * Identity, role, and self-declared capacity — the same three things the team
 * page shows, and deliberately nothing else. No counts, no dates, no ordering
 * that could be read as a judgement: the API returns the roster and this
 * renders it in that order.
 */
export function TeamPanel({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Member[]> => client.listMembers(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the team");

  return (
    <Card
      title="Team"
      action={
        <Link className={utility.actionLink} href="/people">
          All team
        </Link>
      }
    >
      {state.status === "loading" && <LoadingState label="the team" shape="rows" lines={4} />}

      {state.status === "failed" && (
        // headingLevel 3: the card's own title is the h2 above these panels.
        <ErrorState
          title="The team could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
        />
      )}

      {state.status === "ready" &&
        (state.data.length === 0 ? (
          <EmptyState title="Nobody here yet" headingLevel={3}>
            Colleagues appear here once they accept an invitation.
          </EmptyState>
        ) : (
          <ul className={styles.list}>
            {state.data.slice(0, SHOWN).map((member) => (
              <li key={member.userId} className={styles.row}>
                <Avatar name={displayName(member)} size="md" />
                <span className={styles.identity}>
                  <span className={styles.name}>{displayName(member)}</span>
                  <span className={styles.role}>{roleWord(member.role)}</span>
                </span>
                {/* The chip only when there is a declaration to show. Silence
                  about availability is not a state worth drawing. */}
                {member.capacity !== "" && member.capacity !== "not_stated" && (
                  <CapacityChip capacity={member.capacity} />
                )}
              </li>
            ))}
          </ul>
        ))}
    </Card>
  );
}

/** The email's local part when someone has not set a name — a whole address in
 * a narrow row wraps badly and says nothing extra. */
function displayName(member: Member): string {
  if (member.displayName !== null && member.displayName.trim() !== "") return member.displayName;
  const local = member.email.split("@")[0] ?? "";
  return local === "" ? member.email : local;
}

/** The role as a word the reader recognises: the API's "admin" is a value, and
 * a value shown raw reads as a database leaking through. */
function roleWord(role: string): string {
  return role.slice(0, 1).toUpperCase() + role.slice(1);
}
