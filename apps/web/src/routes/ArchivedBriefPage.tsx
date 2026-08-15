"use client";

import type { Brief } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { ClaimList } from "../components/ClaimList.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import { formatPeriod } from "./ArchivePage.js";
import styles from "./BriefPage.module.css";

/**
 * One brief from the archive, exactly as it was written.
 *
 * Shares `BriefPage`'s stylesheet rather than defining its own: this *is* a
 * brief, and a reader following a link from the archive should not be able to
 * tell they have moved to a different screen. The only difference is the
 * heading, which says which period they are looking at.
 */
export function ArchivedBriefPage({ briefId }: { briefId: string }): ReactNode {
  const { activeWorkspace } = useAuth();
  const client = useApiClient();

  const workspaceId = activeWorkspace?.id ?? null;
  const load = useCallback(
    (signal: AbortSignal): Promise<Brief> => {
      if (workspaceId === null) return Promise.reject(new Error("No workspace"));
      return client.getArchivedBrief(workspaceId, briefId, { signal });
    },
    [client, workspaceId, briefId],
  );
  const { state, reload } = useAsync(load, "load this brief");

  if (workspaceId === null) return <LoadingState label="your workspace" />;

  return (
    <>
      <PageHeader
        title={
          state.status === "ready"
            ? formatPeriod(state.data.periodStart, state.data.periodEnd)
            : "Brief"
        }
        description="What CAIRN wrote for this period, kept as it was written."
      />

      <p className={styles.backLink}>
        <Link href="/archive">← All briefs</Link>
      </p>

      {state.status === "loading" && <LoadingState label="this brief" />}

      {state.status === "failed" && (
        <ErrorState title="CAIRN could not load this brief" error={state.error} onRetry={reload} />
      )}

      {state.status === "ready" && <ArchivedBriefBody brief={state.data} />}
    </>
  );
}

function ArchivedBriefBody({ brief }: { brief: Brief }): ReactNode {
  const claims = brief.claims ?? [];

  if (brief.abstained || claims.length === 0) {
    return (
      <EmptyState title="Not enough to summarise">
        {brief.narrative ||
          "CAIRN did not find enough in this period to write a brief it could stand behind."}
      </EmptyState>
    );
  }

  return (
    <>
      <p className={styles.narrative}>{brief.narrative}</p>
      <h2 className={styles.sectionTitle}>What this rests on</h2>
      <ClaimList claims={claims} label="Claims in this brief" />
    </>
  );
}
