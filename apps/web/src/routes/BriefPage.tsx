"use client";

import Link from "next/link";
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
import { formatPeriod } from "./ArchivePage.js";
import utility from "../styles/utility.module.css";
import styles from "./BriefPage.module.css";

/**
 * The Founder Brief — screen 7 of md/15 §4.1. Narrative first, then the claims
 * it rests on with their certainty and sources. Medium-risk under md/05 §A.3, so
 * it auto-generates with a correction affordance.
 *
 * Everything on this page comes from the brief the API returned: the period it
 * covers, when it was written, the prose, and the claims underneath. There are
 * no counters, trends or comparisons, and there is nowhere for one to be added
 * — an overview of the week that scores anybody is the exact surface md/05
 * §B.3.3 says would reclassify the product.
 */
export function BriefPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader
          title="Overview"
          description="Each morning CAIRN writes up what happened across your team, in plain English, with the evidence behind every sentence."
        />
        <EmptyState
          title="Join a workspace to see a brief"
          action={
            <Link className={utility.actionLink} href="/settings">
              Check which account you are using
            </Link>
          }
        >
          A brief describes one team&rsquo;s week, so there is nothing to write until this account
          belongs to a workspace. A colleague can invite you to theirs — and if you expected to be
          in one already, it is worth checking which account you signed in with.
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

  const period =
    state.status === "ready" ? formatPeriod(state.data.periodStart, state.data.periodEnd) : "";

  return (
    <>
      <PageHeader
        // The period the brief covers, taken from the brief itself — not a
        // computed "last 7 days", which would be a claim about data CAIRN may
        // not have. Above the title rather than folded into it, so the heading
        // stays the word the navigation uses for this page.
        {...(period === "" ? {} : { eyebrow: period })}
        title="Overview"
        description="What happened across your team, written in plain English. Every sentence carries how sure CAIRN is of it, and where it came from."
        meta={
          state.status === "ready" && state.data.generatedAt != null
            ? formatGeneratedAt(state.data.generatedAt)
            : undefined
        }
        actions={
          <Link className={utility.actionLink} href="/archive">
            History
          </Link>
        }
      />

      {IS_SAMPLE_CONTENT && <SampleBanner />}

      {/* The skeleton is a paragraph of prose followed by claim rows, because
        that is what arrives. */}
      {state.status === "loading" && <LoadingState label="today's brief" lines={5} />}

      {state.status === "failed" && (
        <ErrorState
          title="Today's brief could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/archive">
              Read an earlier brief
            </Link>
          }
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
      <EmptyState
        title="Not enough to summarise"
        action={
          <Link className={utility.actionLink} href="/feed">
            Read the raw activity
          </Link>
        }
      >
        {brief.narrative ||
          "CAIRN did not find enough in this period to write a brief it could stand behind. It would rather say so than fill the page."}
      </EmptyState>
    );
  }

  const claims = brief.claims ?? [];

  if (claims.length === 0) {
    return (
      <EmptyState
        title="Nothing recorded yet"
        action={
          <Link className={utility.actionLink} href="/trust">
            See what is connected
          </Link>
        }
      >
        No activity has reached CAIRN for this period. Nothing is read until a source is connected
        and switched on, so that is the usual reason a brief has nothing to describe.
      </EmptyState>
    );
  }

  return (
    <article className={styles.brief}>
      <p className={styles.narrative}>{brief.narrative}</p>
      {/* A real heading, so claims are reachable by heading navigation.
        `PageHeader` owns the h1. */}
      <h2 className={styles.sectionTitle}>What this rests on</h2>
      <p className={styles.sectionNote}>
        Every sentence above traces to something the team actually wrote or said. Open a source to
        check it yourself.
      </p>
      <ClaimList claims={claims} label="Claims in today's brief" />

      <p className={styles.footNote}>
        Something here wrong? Correct it in <Link href="/me">your record</Link>, and CAIRN uses the
        correction as evidence rather than overwriting it quietly.
      </p>
    </article>
  );
}

/** `undefined` as the locale, not a hardcoded one: 03/04 means two different
 * days depending on where it is read. */
function formatGeneratedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `Written ${date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
}
