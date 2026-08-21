"use client";

import type { ProjectList } from "@cairn/api-client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { ProjectTile } from "../components/ProjectTile.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./ProjectsPage.module.css";

/**
 * The portfolio: every project in the workspace, alphabetically.
 *
 * **Alphabetical, and that is a decision.** Any activity-derived order — most
 * recently updated, most facts, most anything — ranks the work, and through it
 * the people doing it. The filters below narrow the list; nothing reorders it.
 *
 * A card carries name, purpose, declared state and the claimed sources its
 * evidence resolves through. It deliberately carries no progress figure and no
 * member count: the first would be invented (CAIRN holds no planned-work
 * model) and the second is a number about people.
 */
export function ProjectsPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Projects" description="Everything your team is working on." />
        <EmptyState
          title="Join a workspace to see its projects"
          action={
            <Link className={utility.actionLink} href="/settings">
              Check which account you are using
            </Link>
          }
        >
          Join a workspace to see its projects.
        </EmptyState>
      </>
    );
  }

  return <Portfolio workspaceId={activeWorkspace.id} />;
}

const FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "blocked", label: "Blocked" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "unknown", label: "Not declared" },
] as const;

function Portfolio({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  // Read from the URL, so a filtered portfolio is a link somebody can send —
  // the Overview's state strip links straight into one.
  const selected = useSearchParams().get("state") ?? "";

  const load = useCallback(
    (signal: AbortSignal): Promise<ProjectList> =>
      client.listProjects(workspaceId, selected === "" ? undefined : { state: selected }, {
        signal,
      }),
    [client, workspaceId, selected],
  );
  const { state, reload } = useAsync(load, "load the projects in this workspace");

  const projects = state.status === "ready" ? (state.data.projects ?? []) : [];

  return (
    <>
      <PageHeader
        title="Projects"
        description="Everything your team is working on."
        meta={state.status === "ready" ? projectsLabel(projects.length, selected) : undefined}
      />

      {/* A list of links, not a tab set: each is a real URL, so the browser's
        back button and a shared link both behave. `aria-current` marks the one
        in force, because in a monochrome palette the visual difference is
        weight and it must also exist in the accessibility tree. */}
      <nav className={styles.filters} aria-label="Filter by state">
        <ul className={styles.filterList}>
          {FILTERS.map((filter) => {
            const current = filter.value === selected;
            return (
              <li key={filter.value}>
                <Link
                  className={styles.filter}
                  aria-current={current ? "true" : undefined}
                  href={filter.value === "" ? "/projects" : `/projects?state=${filter.value}`}
                >
                  {filter.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {state.status === "loading" && (
        <LoadingState label="the projects in this workspace" shape="rows" lines={4} />
      )}

      {state.status === "failed" && (
        <ErrorState title="The projects could not be loaded" error={state.error} onRetry={reload} />
      )}

      {state.status === "ready" &&
        (projects.length === 0 ? (
          <EmptyState
            title={selected === "" ? "No projects yet" : "No projects in that state"}
            action={
              selected === "" ? undefined : (
                <Link className={utility.actionLink} href="/projects">
                  Show every project
                </Link>
              )
            }
          >
            {selected === ""
              ? "Create a project to group work and its evidence in one place."
              : "No project is in this state right now."}
          </EmptyState>
        ) : (
          <ul className={styles.grid}>
            {projects.map((project) => (
              <li key={project.id}>
                <ProjectTile project={project} headingLevel={2} />
              </li>
            ))}
          </ul>
        ))}
    </>
  );
}

function projectsLabel(total: number, selected: string): string {
  const noun = total === 1 ? "project" : "projects";
  const count = String(total);
  return selected === "" ? `${count} ${noun}` : `${count} ${noun} in this state`;
}
