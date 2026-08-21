"use client";

import type { ProjectDetail } from "@cairn/api-client";
import { CertaintyBadge, type Certainty } from "@cairn/ui";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Card } from "../components/Card.js";
import { PageHeader } from "../components/PageHeader.js";
import { StateBadge } from "../components/StateBadge.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./ProjectDetailPage.module.css";

/**
 * One project: what it is, what the evidence says, and who is part of it.
 *
 * **The sections are the API's own groups**, not a shape invented here.
 * Delivered work, blockers, open questions and decisions each come back
 * pre-grouped, newest first, with citations — the page renders them and adds
 * nothing.
 *
 * **In-progress and planned work is deliberately an honest empty state.** CAIRN
 * has no planned-work model: no task, no assignment, no estimate exists in the
 * data. A "remaining work" figure would therefore be invented, so the API has
 * no field for one and this page says so in words rather than showing a bar at
 * an arbitrary percentage.
 *
 * **Membership is context.** The people section lists who is part of the
 * project's context and who added them — never what they produced, never a
 * count, never a comparison. Removed members stay listed as closed history,
 * because a shrinking list that silently drops people reads as a project that
 * never had them.
 */
export function ProjectDetailPage({ projectId }: { projectId: string }): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Project" />
        <EmptyState
          title="Join a workspace to see this project"
          action={
            <Link className={utility.actionLink} href="/settings">
              Check which account you are using
            </Link>
          }
        >
          Join a workspace to see this project.
        </EmptyState>
      </>
    );
  }

  return <Detail workspaceId={activeWorkspace.id} projectId={projectId} />;
}

function Detail({ workspaceId, projectId }: { workspaceId: string; projectId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<ProjectDetail> =>
      client.getProject(workspaceId, projectId, { signal }),
    [client, workspaceId, projectId],
  );
  const { state, reload } = useAsync(load, "load this project");

  if (state.status === "loading") {
    return (
      <>
        <PageHeader eyebrow="Project" title="Loading" />
        <LoadingState label="this project" shape="rows" lines={6} />
      </>
    );
  }

  if (state.status === "failed") {
    return (
      <>
        <PageHeader eyebrow="Project" title="Project" />
        <ErrorState
          title="This project could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/projects">
              Back to all projects
            </Link>
          }
        />
      </>
    );
  }

  const project = state.data;
  const rollup = project.rollup;

  return (
    <>
      <PageHeader
        eyebrow="Project"
        title={project.name}
        {...(project.purpose == null ? {} : { description: project.purpose })}
        {...(declaredBy(project) === undefined ? {} : { meta: declaredBy(project) })}
        actions={
          <Link className={utility.actionLink} href="/projects">
            All projects
          </Link>
        }
      />

      <div className={styles.stack}>
        <Card title="Overview">
          <div className={styles.overview}>
            <StateBadge state={project.state} />
            {project.archivedAt != null && (
              <span className={styles.archived}>Archived — its evidence still works</span>
            )}
          </div>
          <h3 className={styles.subheading}>Sources</h3>
          {(project.sources ?? []).length === 0 ? (
            <p className={styles.note}>
              No sources yet. An owner or admin links a repository or channel to bring its work in.
            </p>
          ) : (
            <ul className={styles.chips}>
              {(project.sources ?? []).map((source) => (
                <li className={styles.chip} key={source.value}>
                  {source.value}
                  {source.addedBy != null && (
                    <span className={styles.chipMeta}> · claimed by {source.addedBy}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <FactSection
          title="Delivered work"
          description="Finished work, newest first."
          facts={rollup.delivered ?? []}
          empty="Nothing has been recorded as delivered under this project yet."
        />

        <Card title="In progress and planned work" description="Not tracked.">
          <EmptyState title="CAIRN does not track planned work" headingLevel={3}>
            CAIRN records what your tools report, and no tool here reports planned work. Showing a
            &ldquo;remaining&rdquo; figure would mean guessing, so we do not.
          </EmptyState>
        </Card>

        <FactSection
          title="Blockers"
          description="What is stuck, and why."
          facts={rollup.blockers ?? []}
          empty="No blockers have been recorded under this project."
        />

        <FactSection
          title="Open questions"
          description="Waiting on an answer."
          facts={rollup.openQuestions ?? []}
          empty="No open questions have been recorded under this project."
        />

        <FactSection
          title="Decisions"
          description="What your team agreed, and where."
          facts={rollup.decisions ?? []}
          empty="No decisions have been recorded under this project."
        />

        <Card title="People" description="Who is involved. Being listed here assigns no work.">
          {(project.members ?? []).length === 0 ? (
            <EmptyState title="Nobody has been added yet" headingLevel={3}>
              An owner or admin can add people. Adding someone assigns them no work.
            </EmptyState>
          ) : (
            <ul className={styles.people}>
              {(project.members ?? []).map((member) => (
                <li className={styles.person} key={`${member.personId}-${member.addedAt}`}>
                  <div className={styles.personName}>
                    {member.displayName}
                    {member.projectRole != null && (
                      <span className={styles.personRole}>{member.projectRole}</span>
                    )}
                  </div>
                  <p className={styles.personMeta}>
                    {member.addedBy != null
                      ? `Added by ${member.addedBy} on ${asDate(member.addedAt)}`
                      : `Added on ${asDate(member.addedAt)}`}
                    {member.removedAt != null &&
                      ` · Removed${member.removedBy != null ? ` by ${member.removedBy}` : ""} on ${asDate(member.removedAt)}`}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

/** One rollup group: cited rows, or an honest empty state. */
function FactSection({
  title,
  description,
  facts,
  empty,
}: {
  title: string;
  description: string;
  facts: NonNullable<ProjectDetail["rollup"]["delivered"]>;
  empty: string;
}): ReactNode {
  return (
    <Card title={title} description={description}>
      {facts.length === 0 ? (
        <EmptyState title="Nothing recorded" headingLevel={3}>
          {empty}
        </EmptyState>
      ) : (
        <ul className={styles.facts}>
          {facts.map((fact, index) => (
            <li className={styles.fact} key={`${fact.statement}-${String(index)}`}>
              <p className={styles.factStatement}>{fact.statement}</p>
              <p className={styles.factMeta}>
                <FactCertainty value={fact.certainty} />
                {(fact.sources ?? []).map((source) =>
                  source.url != null ? (
                    <a className={styles.source} href={source.url} key={source.evidenceId}>
                      {source.evidenceId}
                    </a>
                  ) : (
                    <span className={styles.source} key={source.evidenceId}>
                      {source.evidenceId}
                    </span>
                  ),
                )}
                {fact.occurredAt != null && (
                  <span className={styles.factTime}>{asDate(fact.occurredAt)}</span>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * The API types a project fact's certainty as a plain string, deliberately: a
 * server that gains a new tier should render it rather than fail to
 * deserialise. So this narrows with a guard instead of a cast - a tier the
 * badge knows gets the badge, and anything else is shown as its own word
 * rather than being coerced into a tier it is not.
 */
function isTier(value: string): value is Certainty {
  return value === "verified" || value === "observed" || value === "suggested";
}

function FactCertainty({ value }: { value: string }): ReactNode {
  return isTier(value) ? (
    <CertaintyBadge certainty={value} />
  ) : (
    <span className={styles.source}>{value}</span>
  );
}

function declaredBy(project: ProjectDetail): string | undefined {
  if (project.stateDeclaredAt == null) return "Nobody has declared a state for this project";
  const who = project.stateDeclaredBy ?? "somebody in this workspace";
  return `State declared by ${who} on ${asDate(project.stateDeclaredAt)}`;
}

function asDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
