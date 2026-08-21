"use client";

import type { Member, ProjectList } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Avatar } from "../components/Avatar.js";
import { CapacityChip } from "../components/CapacityChip.js";
import { Card } from "../components/Card.js";
import { PageHeader } from "../components/PageHeader.js";
import { ProjectTile } from "../components/ProjectTile.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./DashboardPage.module.css";

/**
 * The dashboard: who is here, and what they are working on.
 *
 * Two subjects, deliberately. A person card opens that person's record — their
 * role, what they have said about their own availability, and which projects
 * they are part of. A project card opens the project — its evidence, and who
 * is involved with the role each of them holds there. The two directions of
 * one relationship, both reachable from this screen.
 *
 * **Nothing here measures anybody.** A person card carries identity, a role
 * and a self-declared capacity; it carries no count, no volume, no "last
 * active" and no comparison, and there is no arrangement of this screen that
 * could produce one (md/05 §B.2, §B.3.3). Evidence, counts of work and the
 * daily narrative live on Activity and the Brief, where they read as what they
 * are.
 */
export function DashboardPage(): ReactNode {
  const { activeWorkspace, session } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Dashboard" description="Your team and its projects." />
        <EmptyState title="Join a workspace to get started">
          Join a workspace and your team&rsquo;s work appears here.
        </EmptyState>
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={today()}
        title={greeting(session?.user.displayName ?? null)}
        description="Your team and the projects they are working on."
        actions={
          <Link className={styles.primaryAction} href="/brief">
            View today&rsquo;s brief
          </Link>
        }
      />

      <div className={styles.stack}>
        <TeamSection workspaceId={activeWorkspace.id} />
        <ProjectsSection workspaceId={activeWorkspace.id} />
      </div>
    </>
  );
}

/** "Good evening, Ali" — or the plain form when the session carries no name.
 * Never "Welcome back", which claims to know something about a previous
 * visit. */
function greeting(name: string | null): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  return name === null ? `Good ${part}` : `Good ${part}, ${name}`;
}

/** `undefined` as the locale, deliberately: a fixed one renders the wrong date
 * format for most of the people reading it. */
function today(): string {
  return new Date().toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

const ROLE_LABEL: Readonly<Record<string, string>> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  viewer: "Viewer",
};

/**
 * Everyone in the workspace, one card each.
 *
 * In the order the API returns them, which is the order they joined — not
 * sorted by anything that could read as importance. An ordering is a ranking
 * when the things ordered are people.
 */
function TeamSection({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Member[]> => client.listMembers(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the team");

  return (
    <Card
      title="Team"
      description="Everyone in this workspace."
      action={
        <Link className={utility.actionLink} href="/people">
          Team page
        </Link>
      }
    >
      {state.status === "loading" && <LoadingState label="the team" shape="rows" lines={3} />}

      {state.status === "failed" && (
        <ErrorState title="The team could not be loaded" error={state.error} onRetry={reload} />
      )}

      {state.status === "ready" &&
        (state.data.length === 0 ? (
          <EmptyState title="Nobody here yet" headingLevel={3}>
            Invite a colleague from workspace settings.
          </EmptyState>
        ) : (
          <ul className={styles.cardGrid}>
            {state.data.map((member) => (
              <li key={member.userId}>
                <PersonCard member={member} />
              </li>
            ))}
          </ul>
        ))}
    </Card>
  );
}

/**
 * One person, as a card.
 *
 * The name links to their record when the workspace has a person row for them.
 * A member nobody has mentioned in any source has none yet, and the card stays
 * a card rather than becoming a link to nothing.
 */
function PersonCard({ member }: { member: Member }): ReactNode {
  const name = member.displayName ?? member.email.split("@")[0] ?? member.email;
  const role = ROLE_LABEL[member.role] ?? member.role;
  const personId = member.personId ?? null;

  return (
    <article className={styles.personCard}>
      <Avatar name={name} size="md" />
      <div className={styles.personBody}>
        <h3 className={styles.personName}>
          {personId === null ? (
            name
          ) : (
            <Link className={styles.personLink} href={`/people/${personId}`}>
              {name}
            </Link>
          )}
        </h3>
        <p className={styles.personRole}>{role}</p>
        {member.capacity !== "not_stated" && <CapacityChip capacity={member.capacity} />}
      </div>
    </article>
  );
}

/** Every project, one card each, in the order the API returns — alphabetical.
 * Any activity-derived order would rank the work and, through it, the people
 * doing it. */
function ProjectsSection({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<ProjectList> =>
      client.listProjects(workspaceId, undefined, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the projects");

  const projects = state.status === "ready" ? (state.data.projects ?? []) : [];

  return (
    <Card
      title="Projects"
      description="What the team is working on."
      action={
        <Link className={utility.actionLink} href="/projects">
          All projects
        </Link>
      }
    >
      {state.status === "loading" && <LoadingState label="the projects" shape="rows" lines={3} />}

      {state.status === "failed" && (
        <ErrorState title="Projects could not be loaded" error={state.error} onRetry={reload} />
      )}

      {state.status === "ready" &&
        (projects.length === 0 ? (
          <EmptyState title="No projects yet" headingLevel={3}>
            Create a project to group work and its evidence in one place.
          </EmptyState>
        ) : (
          <ul className={styles.cardGrid}>
            {projects.map((project) => (
              <li key={project.id}>
                <ProjectTile project={project} />
              </li>
            ))}
          </ul>
        ))}
    </Card>
  );
}
