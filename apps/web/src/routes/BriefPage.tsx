"use client";

import { useCallback, useMemo, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { contentSourceFor, IS_SAMPLE_CONTENT } from "../brief/adapter.js";
import type { Brief } from "../brief/types.js";
import { ClaimList } from "../components/ClaimList.js";
import { PageHeader } from "../components/PageHeader.js";
import { SampleBanner } from "../components/SampleBanner.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./BriefPage.module.css";

/**
 * The Founder Brief — screen 7 of md/15 §4.1. Narrative first, then the claims
 * it rests on with their certainty and sources. Medium-risk under md/05 §A.3, so
 * it auto-generates with a correction affordance; screen 10 does not exist yet.
 */
export function BriefPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Brief" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is nothing to summarise. An
          invitation from a colleague, or creating a workspace, will fill this page.
        </EmptyState>
      </>
    );
  }

  // Loading lives in a child so its hooks can depend on an id known to exist.
  return <WorkspaceBrief workspaceId={activeWorkspace.id} />;
}

function WorkspaceBrief({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  // Memoised so the callback below is stable and `useAsync` does not re-fetch.
  const content = useMemo(() => contentSourceFor(client), [client]);
  const load = useCallback(
    (signal: AbortSignal): Promise<Brief> => content.getBrief(workspaceId, signal),
    [content, workspaceId],
  );
  const { state, reload } = useAsync(load, "load today's brief");

  return (
    <>
      <PageHeader
        title="Brief"
        description="What happened across your team, written up in plain English. Every sentence carries how sure CAIRN is of it, and where it came from."
        meta={
          state.status === "ready" && state.data.generatedAt != null
            ? formatGeneratedAt(state.data.generatedAt)
            : undefined
        }
      />

      {IS_SAMPLE_CONTENT && <SampleBanner />}

      {state.status === "loading" && <LoadingState label="today's brief" lines={5} />}

      {state.status === "failed" && (
        <ErrorState
          title="Today's brief could not be loaded"
          error={state.error}
          onRetry={reload}
        />
      )}

      {state.status === "ready" && <BriefBody brief={state.data} />}
    </>
  );
}

function BriefBody({ brief }: { brief: Brief }): ReactNode {
  // Abstention is its own state: collapsing it into "no claims" would let a
  // pipeline that declined to answer read as a quiet week.
  if (brief.abstained) {
    return (
      <EmptyState title="Not enough to summarise">
        {brief.narrative ||
          "CAIRN did not find enough in this period to write a brief it could stand behind. It would rather say so than fill the page."}
      </EmptyState>
    );
  }

  const claims = brief.claims ?? [];

  if (claims.length === 0) {
    return (
      <EmptyState title="Nothing recorded yet">
        No activity has reached CAIRN for this period. Once a source is connected and the team is
        working, the brief appears here each morning.
      </EmptyState>
    );
  }

  return (
    <>
      <p className={styles.narrative}>{brief.narrative}</p>
      {/* A real heading, so claims are reachable by heading navigation.
        `PageHeader` owns the h1. */}
      <h2 className={styles.sectionTitle}>What this rests on</h2>
      <ClaimList claims={claims} label="Claims in today's brief" />
    </>
  );
}

/** `undefined` as the locale, not a hardcoded one: 03/04 means two different
 * days depending on where it is read. */
function formatGeneratedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `Written ${date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
}
