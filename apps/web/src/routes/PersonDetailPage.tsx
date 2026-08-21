"use client";

import type { Member, ProjectDetail } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import type { Fact } from "../brief/types.js";
import { Avatar } from "../components/Avatar.js";
import { CapacityChip } from "../components/CapacityChip.js";
import { Card } from "../components/Card.js";
import { EvidenceRow } from "../components/EvidenceRow.js";
import { PageHeader } from "../components/PageHeader.js";
import { StateBadge } from "../components/StateBadge.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./PersonDetailPage.module.css";

/**
 * One colleague: who they are, which projects they are part of, and the cited
 * work that names them.
 *
 * **The field set is the whole boundary.** Identity, the workspace role that
 * governs settings, a self-declared availability, project membership, and
 * evidence that cites them — nothing else. Every one of those is a statement
 * somebody made, with a source a reader can open. What is deliberately absent
 * is the second layer: how much of it there is, how it compares, how fresh it
 * is. A page about a person that answers "how much" is a page you check on
 * somebody with, and everything after that first number is a negotiation about
 * where the threshold sits.
 *
 * **Recent work is cited facts, newest first, and nothing more.** No total, no
 * cadence, no claim about what this person is doing at this moment — CAIRN
 * knows what its sources reported, which is a different thing from what
 * somebody is doing now, and a heading that blurs the two is the whole failure.
 *
 * **Removed memberships stay listed as closed history**, matching the project
 * page: a list that silently drops the projects somebody left reads as a
 * colleague who was never on them.
 */
export function PersonDetailPage({ personId }: { personId: string }): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Person" />
        <EmptyState
          title="Join a workspace to see this person"
          action={
            <Link className={utility.actionLink} href="/settings">
              Check which account you are using
            </Link>
          }
        >
          Join a workspace to see this person.
        </EmptyState>
      </>
    );
  }

  return <Detail workspaceId={activeWorkspace.id} personId={personId} />;
}

/**
 * How many projects one page view will open to find this person's memberships.
 *
 * BACKEND GAP: there is no endpoint returning a person's project memberships
 * directly, so this page reconstructs them by reading the portfolio and then
 * opening each project. That is one request per project, which cannot be let
 * loose on a large workspace — hence the cap, and hence the honest line the
 * page renders when the portfolio is bigger than it. The next phase should add
 * a memberships-for-a-person endpoint and this whole fan-out, cap and caveat
 * should be deleted with it.
 */
const PROJECTS_EXAMINED = 20;

/**
 * How many cited facts the work section asks for.
 *
 * A short readable column, not a feed. A section that keeps going invites
 * reading its length as a measurement of the person it is about, which is
 * exactly the reading this page exists to refuse.
 */
const RECENT_WORK_SHOWN = 8;

/** The workspace role, in the word the settings screens use for it. A role the
 * client does not recognise renders as its own word rather than being coerced
 * into one of these. */
const ROLE_WORD: Readonly<Record<string, string>> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  viewer: "Viewer",
};

/** One project this person is, or was, part of. */
interface Membership {
  projectId: string;
  projectName: string;
  /** The role they would use for themselves here ("Backend"), or null. */
  projectRole: string | null;
  /** The project's own declared state. It describes the project, never how
   * things are going for the person in this row. */
  projectState: string;
  removed: boolean;
}

/** Who this person is, as the workspace has it. Null when nothing names them. */
interface Profile {
  displayName: string;
  role: string | null;
  capacity: string | null;
  email: string | null;
}

interface PersonView {
  profile: Profile | null;
  memberships: Membership[];
  /** False when the fan-out was capped — see `PROJECTS_EXAMINED`. */
  everyProjectExamined: boolean;
}

function Detail({ workspaceId, personId }: { workspaceId: string; personId: string }): ReactNode {
  const client = useApiClient();

  const load = useCallback(
    async (signal: AbortSignal): Promise<PersonView> => {
      // The two independent reads go together; the fan-out below depends on one
      // of them and so has to wait.
      const [members, portfolio] = await Promise.all([
        client.listMembers(workspaceId, { signal }),
        client.listProjects(workspaceId, undefined, { signal }),
      ]);

      const projects = portfolio.projects ?? [];
      const examined = projects.slice(0, PROJECTS_EXAMINED);
      const details = await Promise.all(
        examined.map((project): Promise<ProjectDetail> =>
          client.getProject(workspaceId, project.id, { signal }),
        ),
      );

      const memberships: Membership[] = [];
      let nameFromProject: string | null = null;

      for (const project of details) {
        const entries = (project.members ?? []).filter((entry) => entry.personId === personId);
        if (entries.length === 0) continue;

        // A person can be added, removed and added again, so one project can
        // hold several rows for them. One row per project here, and a current
        // membership wins: somebody who is on the project now should not read
        // as removed because they once were.
        const entry = entries.find((candidate) => candidate.removedAt == null) ?? entries[0];
        if (entry === undefined) continue;

        nameFromProject ??= entry.displayName;
        memberships.push({
          projectId: project.id,
          projectName: project.name,
          projectRole: entry.projectRole ?? null,
          projectState: project.state,
          removed: entry.removedAt != null,
        });
      }

      return {
        profile: profileOf(members, personId, nameFromProject),
        memberships,
        everyProjectExamined: projects.length <= PROJECTS_EXAMINED,
      };
    },
    [client, workspaceId, personId],
  );

  const { state, reload } = useAsync(load, "load this person");

  if (state.status === "loading") {
    return (
      <>
        <PageHeader eyebrow="Person" title="Loading" />
        <LoadingState label="this person" shape="rows" lines={4} />
      </>
    );
  }

  if (state.status === "failed") {
    return (
      <>
        <PageHeader eyebrow="Person" title="Person" />
        <ErrorState
          title="This person could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/people">
              All team
            </Link>
          }
        />
      </>
    );
  }

  const { profile, memberships, everyProjectExamined } = state.data;

  // Nothing in the workspace names this person: a stale link or somebody who
  // has left. Say so plainly rather than draw a card of blanks.
  if (profile === null) {
    return (
      <>
        <PageHeader eyebrow="Person" title="Person" />
        <EmptyState
          title="Person not found"
          action={
            <Link className={utility.actionLink} href="/people">
              All team
            </Link>
          }
        >
          Nobody in this workspace matches this link.
        </EmptyState>
      </>
    );
  }

  return (
    <div className={styles.stack}>
      {/*
       * The hero card *is* this page's header, so it owns the `<h1>`. A
       * PageHeader above it would set the same name twice on one screen — once
       * as the page title, once as the subject of the card — and a person's
       * name echoed straight back at the reader is the small duplication that
       * makes a profile feel unfinished.
       */}
      <Card className={styles.hero}>
        <div className={styles.heroBand}>
          <Avatar name={profile.displayName} size="md" />

          <div className={styles.heroText}>
            <span className={styles.eyebrow}>Person</span>
            <h1 className={styles.heroName}>{profile.displayName}</h1>

            <div className={styles.heroFacts}>
              {profile.role != null && (
                <span className={styles.roleWord}>{ROLE_WORD[profile.role] ?? profile.role}</span>
              )}
              {/* Only when somebody declared one. `not_stated` is the absence of
                a declaration, and a chip in front of it invites reading the
                absence as an answer. */}
              {profile.capacity != null && profile.capacity !== "not_stated" && (
                <CapacityChip capacity={profile.capacity} />
              )}
            </div>

            {profile.email == null ? (
              // Somebody a source named who has never signed in. Saying why
              // keeps the blank from reading as a field the reader is supposed
              // to go and fill in.
              <p className={styles.noAccount}>
                No account yet — appears in your team&rsquo;s sources
              </p>
            ) : (
              <a className={styles.email} href={`mailto:${profile.email}`}>
                {profile.email}
              </a>
            )}
          </div>

          <Link className={utility.actionLink} href="/people">
            All team
          </Link>
        </div>
      </Card>

      <Card title="Projects" description="Projects this person is part of.">
        {memberships.length === 0 ? (
          <EmptyState title="Not in any project yet" headingLevel={3}>
            An owner or admin can add this person to a project.
          </EmptyState>
        ) : (
          <ul className={styles.projects}>
            {memberships.map((membership) => (
              <li className={styles.project} key={membership.projectId}>
                <Link className={styles.projectName} href={`/projects/${membership.projectId}`}>
                  {membership.projectName}
                </Link>
                <span className={styles.projectRole}>
                  {membership.projectRole ?? "No role set"}
                </span>
                <StateBadge state={membership.projectState} />
                {membership.removed && <span className={styles.removed}>Removed</span>}
              </li>
            ))}
          </ul>
        )}
        {!everyProjectExamined && (
          <p className={styles.caveat}>
            Not every project in this workspace was checked, so this list may be incomplete.
          </p>
        )}
      </Card>

      <RecentWork workspaceId={workspaceId} personId={personId} />
    </div>
  );
}

/**
 * The cited work that names this person, newest first.
 *
 * Its own component with its own `useAsync`, exactly as the project page's
 * sections are. The facts endpoint is a separate read, and this person's
 * identity and memberships should still be on the screen when it is the read
 * that fails — folding it into the parent would turn one broken endpoint into
 * a blank profile.
 */
function RecentWork({
  workspaceId,
  personId,
}: {
  workspaceId: string;
  personId: string;
}): ReactNode {
  const client = useApiClient();

  const load = useCallback(
    async (signal: AbortSignal): Promise<Fact[]> => {
      const page = await client.listFacts(
        workspaceId,
        { person: [personId], limit: RECENT_WORK_SHOWN },
        { signal },
      );
      return page.items ?? [];
    },
    [client, workspaceId, personId],
  );

  const { state, reload } = useAsync(load, "load recent work");

  return (
    <Card title="Recent work" description="Work that cites this person.">
      {state.status === "loading" && <LoadingState label="recent work" shape="rows" lines={3} />}

      {state.status === "failed" && (
        <ErrorState
          title="Recent work could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
        />
      )}

      {state.status === "ready" &&
        (state.data.length === 0 ? (
          <EmptyState title="Nothing cites this person yet." headingLevel={3}>
            Evidence that names them will appear here.
          </EmptyState>
        ) : (
          <ul className={styles.work}>
            {state.data.map((fact) => (
              <li className={styles.workItem} key={fact.id}>
                {/* The person is the subject of the page, so their name on
                  every row is noise rather than provenance. */}
                <EvidenceRow fact={fact} showPerson={false} />
              </li>
            ))}
          </ul>
        ))}
    </Card>
  );
}

/**
 * Who this person is, preferring the workspace's own record of them.
 *
 * The fallback matters: somebody can appear on a project without still being a
 * member of the workspace, and a project membership carries their name. A name
 * with no email beside it is a truer page than no page at all.
 */
function profileOf(
  members: Member[],
  personId: string,
  nameFromProject: string | null,
): Profile | null {
  const member = members.find((candidate) => candidate.personId === personId);

  if (member !== undefined) {
    return {
      displayName: member.displayName ?? member.email,
      role: member.role,
      capacity: member.capacity,
      email: member.email,
    };
  }

  if (nameFromProject === null) return null;

  return { displayName: nameFromProject, role: null, capacity: null, email: null };
}
