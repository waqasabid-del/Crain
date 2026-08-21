"use client";

import type { ProjectList } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Card } from "../components/Card.js";
import { Field } from "../components/Field.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { StatusNote } from "../components/StatusNote.js";
import { describeError, type DescribedError } from "../errors.js";
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

/**
 * Four, and only four.
 *
 * A filter row is a claim about what states exist. "Blocked" and "Not
 * declared" are real values the API can return - a tile still shows them - but
 * they are not choices a reader needs at the top of the portfolio, and six
 * pills read as a taxonomy rather than a way in.
 */
const FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
  { value: "paused", label: "Paused" },
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
  const { activeRole } = useAuth();

  // Decides what to *offer*, never what to allow: the API holds the permission
  // and refuses a request this screen was wrong to show.
  const canManage = activeRole === "owner" || activeRole === "admin";

  const projects = state.status === "ready" ? (state.data.projects ?? []) : [];

  return (
    <>
      <PageHeader
        title="Projects"
        description="Everything your team is working on."
        meta={state.status === "ready" ? projectsLabel(projects.length, selected) : undefined}
      />

      {canManage && <NewProject workspaceId={workspaceId} onCreated={reload} />}

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

/**
 * Create a project.
 *
 * A disclosure rather than a dialog, for the same reason the team page's
 * invite is: two fields do not justify an overlay, a focus trap and an inert
 * background. A new project starts with no declared state - nobody has said
 * what it is yet, and the API's default says so honestly.
 */
function NewProject({
  workspaceId,
  onCreated,
}: {
  workspaceId: string;
  onCreated: () => void;
}): ReactNode {
  const client = useApiClient();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  async function submit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setProblem(null);
    setCreated(null);
    setSaving(true);
    try {
      const project = await client.createProject(workspaceId, {
        name,
        // Spread rather than sending an empty string: `exactOptionalPropertyTypes`
        // aside, a blank purpose is an absent one, not a purpose that is "".
        ...(purpose.trim() === "" ? {} : { purpose }),
      });
      setCreated(project.name);
      setName("");
      setPurpose("");
      onCreated();
    } catch (error: unknown) {
      setProblem(describeError(error, "create this project"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className={styles.create}>
      <div className={styles.createHead}>
        <div>
          <h2 className={styles.createTitle}>New project</h2>
          <p className={styles.createNote}>Group work and its evidence under one name.</p>
        </div>
        <Button
          type="button"
          variant={open ? "secondary" : "primary"}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => {
            setOpen(!open);
          }}
        >
          {open ? "Cancel" : "New project"}
        </Button>
      </div>

      {open && (
        <form className={styles.createForm} id={panelId} onSubmit={(event) => void submit(event)}>
          <Field
            label="Name"
            required
            maxLength={200}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          <Field
            label="Purpose"
            hint="One sentence on what this project is for. Optional."
            maxLength={500}
            value={purpose}
            onChange={(event) => {
              setPurpose(event.target.value);
            }}
          />
          <Button type="submit" loading={saving}>
            Create project
          </Button>
          {problem !== null && <InlineProblem error={problem} />}
        </form>
      )}

      {created !== null && <StatusNote>{created} was created.</StatusNote>}
    </Card>
  );
}

function projectsLabel(total: number, selected: string): string {
  const noun = total === 1 ? "project" : "projects";
  const count = String(total);
  return selected === "" ? `${count} ${noun}` : `${count} ${noun} in this state`;
}
