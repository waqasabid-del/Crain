"use client";

import type { BriefArchive } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./ArchivePage.module.css";

/**
 * Past briefs, as they were written. An archive means nothing if its entries
 * change, so a finished period is written once and never re-generated — the API
 * enforces that, and this screen is the reason it matters.
 */
export function ArchivePage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return <LoadingState label="your workspace" shape="rows" />;
  }

  return <WorkspaceArchive workspaceId={activeWorkspace.id} />;
}

function WorkspaceArchive({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<BriefArchive> =>
      client.listBriefs(workspaceId, undefined, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your past briefs");

  return (
    <>
      <PageHeader
        title="History"
        description="Every brief CAIRN has written for this workspace, exactly as it was written. A finished period is never re-generated, so what you read here is what the team read at the time."
        actions={
          <Link className={utility.actionLink} href="/">
            Today&rsquo;s brief
          </Link>
        }
      />

      {state.status === "loading" && (
        <LoadingState label="your past briefs" shape="rows" lines={5} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="Your history could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/">
              Read today&rsquo;s brief
            </Link>
          }
        />
      )}

      {state.status === "ready" && <ArchiveList archive={state.data} />}
    </>
  );
}

function ArchiveList({ archive }: { archive: BriefArchive }): ReactNode {
  const items = archive.items ?? [];

  if (items.length === 0) {
    return (
      <EmptyState
        title="No briefs yet"
        action={
          <Link className={utility.actionLink} href="/">
            Read today&rsquo;s brief
          </Link>
        }
      >
        A brief is kept once the period it covers has ended, so today&rsquo;s appears here tomorrow
        and stays unchanged after that.
      </EmptyState>
    );
  }

  return (
    <ul className={styles.list} aria-label="Past briefs">
      {items.map((item) => (
        <li key={item.id} className={styles.item}>
          {/* The whole row is the link target: a "read more" at the end of a
            wide row is a small target. */}
          <Link className={styles.link} href={`/archive/${item.id}`}>
            <span className={styles.period}>{formatPeriod(item.periodStart, item.periodEnd)}</span>
            <span className={styles.excerpt}>
              {item.abstained
                ? "CAIRN did not find enough in this period to write a brief it could stand behind."
                : item.excerpt}
            </span>
            <span className={styles.count}>
              {item.claimCount} {item.claimCount === 1 ? "claim" : "claims"}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function formatPeriod(start: string, end: string): string {
  const from = new Date(start);
  const to = new Date(end);
  const day = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long" });

  // Labelled by duration, not calendar boundaries: a 06:00-to-06:00 brief spans
  // two dates and is one day of work. The tolerance absorbs clock drift.
  const oneDay = 24 * 60 * 60 * 1000;
  if (to.getTime() - from.getTime() <= oneDay + 1000) return day.format(from);

  return `${day.format(from)} – ${day.format(to)}`;
}
