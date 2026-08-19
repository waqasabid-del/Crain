"use client";

import Link from "next/link";
import { useCallback, useMemo, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { contentSourceFor, IS_SAMPLE_CONTENT, type ContentSource } from "../brief/adapter.js";
import type { Brief, Fact } from "../brief/types.js";
import { ClaimList } from "../components/ClaimList.js";
import { Section } from "../components/Section.js";
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
 * no counters, trends or comparisons about people, and there is nowhere for one
 * to be added — an overview of the week that scores anybody is the exact
 * surface md/05 §B.3.3 says would reclassify the product.
 *
 * Beside the brief sits a rail of *system* panels — the latest recorded facts,
 * the sources the record currently draws on, and the standing places to go
 * next. They describe what the system is doing, never how a person is doing:
 * the one count on this screen belongs to a section heading, and no number is
 * welded to a name.
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

      <div className={styles.layout}>
        <div className={styles.primary}>
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
        </div>

        {/* `aside`, not a second column of the article: these panels are
          orientation around the brief, and a screen reader should be able to
          skip them as one complementary landmark. Each panel loads and fails
          on its own — a broken feed must not take the brief down with it. */}
        <aside className={styles.rail} aria-label="Around this brief">
          <ActivityPanel content={content} workspaceId={workspaceId} />
          <SourcesPanel content={content} workspaceId={workspaceId} />
          <GoToPanel />
        </aside>
      </div>
    </>
  );
}

/** How many recent facts the rail shows before pointing at the full feed. */
const ACTIVITY_PREVIEW = 5;

/**
 * The newest recorded facts, as one-line provenance — statement and source,
 * never a number against a name. A preview of `/feed`, not a rival to it: it
 * exists so "is anything reaching CAIRN right now?" is answerable from the
 * overview without a navigation.
 */
function ActivityPanel({
  content,
  workspaceId,
}: {
  content: ContentSource;
  workspaceId: string;
}): ReactNode {
  const load = useCallback(
    (signal: AbortSignal) => content.getFacts(workspaceId, { limit: ACTIVITY_PREVIEW }, signal),
    [content, workspaceId],
  );
  const { state, reload } = useAsync(load, "load recent activity");

  return (
    <Section
      title="Latest activity"
      className={styles.panel ?? ""}
      headingClassName={styles.panelTitle ?? ""}
    >
      {state.status === "loading" && (
        <LoadingState label="recent activity" shape="rows" lines={3} />
      )}
      {state.status === "failed" && (
        <ErrorState
          title="Recent activity could not be loaded"
          error={state.error}
          onRetry={reload}
        />
      )}
      {state.status === "ready" &&
        (state.data.items.length === 0 ? (
          <p className={styles.panelEmpty}>
            Nothing has been recorded yet. Activity appears here the moment a connected source
            produces something.
          </p>
        ) : (
          <ul className={styles.panelList}>
            {state.data.items.slice(0, ACTIVITY_PREVIEW).map((fact) => (
              <li className={styles.panelItem} key={fact.id}>
                <span className={styles.panelStatement}>{fact.statement}</span>
                <span className={styles.panelMeta}>{factProvenance(fact)}</span>
              </li>
            ))}
          </ul>
        ))}
      <p className={styles.panelFoot}>
        <Link className={utility.actionLink} href="/feed">
          All activity
        </Link>
      </p>
    </Section>
  );
}

/** "github", or "github and meeting" — where a fact's evidence came from. */
function factProvenance(fact: Fact): string {
  const sources = [...new Set((fact.sources ?? []).map((source) => source.source))];
  if (sources.length === 0) return "unsourced";
  return sources.join(" and ");
}

/**
 * Which sources the record currently draws on — read from the facts themselves
 * via the facets, not from a configuration screen, so an empty list means "no
 * evidence" rather than "not set up". System health stated as provenance.
 */
function SourcesPanel({
  content,
  workspaceId,
}: {
  content: ContentSource;
  workspaceId: string;
}): ReactNode {
  const load = useCallback(
    (signal: AbortSignal) => content.getFacets(workspaceId, signal),
    [content, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the record's sources");

  return (
    <Section
      title="Where this comes from"
      className={styles.panel ?? ""}
      headingClassName={styles.panelTitle ?? ""}
    >
      {state.status === "loading" && (
        <LoadingState label="the record's sources" shape="rows" lines={2} />
      )}
      {state.status === "failed" && (
        <ErrorState title="Sources could not be read" error={state.error} onRetry={reload} />
      )}
      {state.status === "ready" &&
        ((state.data.sources ?? []).length === 0 ? (
          <p className={styles.panelEmpty}>
            No source has produced evidence yet, so today&rsquo;s record rests on nothing. Once a
            connected tool produces something, it is named here.
          </p>
        ) : (
          <ul className={styles.panelList}>
            {(state.data.sources ?? []).map((source) => (
              <li className={styles.panelItem} key={source}>
                <span className={styles.panelStatement}>{source}</span>
              </li>
            ))}
          </ul>
        ))}
      <p className={styles.panelFoot}>
        <Link className={utility.actionLink} href="/trust">
          How CAIRN treats this data
        </Link>
      </p>
    </Section>
  );
}

/** Standing destinations from the overview. Static, so it has no states. */
function GoToPanel(): ReactNode {
  return (
    <Section
      title="Go to"
      className={styles.panel ?? ""}
      headingClassName={styles.panelTitle ?? ""}
    >
      <ul className={styles.panelList}>
        <li className={styles.panelItem}>
          <Link className={utility.actionLink} href="/me">
            Your record and corrections
          </Link>
        </li>
        <li className={styles.panelItem}>
          <Link className={utility.actionLink} href="/archive">
            Earlier briefs
          </Link>
        </li>
        <li className={styles.panelItem}>
          <Link className={utility.actionLink} href="/people">
            The team
          </Link>
        </li>
      </ul>
    </Section>
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
