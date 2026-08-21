"use client";

import { ApiError, type Facets, type ProjectDetail, type ProjectList } from "@cairn/api-client";
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
        <EmptyState title="Join a workspace to see its projects">
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
 * The states a creator may declare, led by the honest absence.
 *
 * "Not set yet" is first and is the default *on purpose*. A state in CAIRN is a
 * human's declaration — the API stamps it with who said it and when — so a
 * dropdown arriving pre-set to "Active" would put a word in the creator's mouth
 * and then attribute it to them. An undeclared project is a true statement
 * about a project nobody has described yet.
 */
const NEW_PROJECT_STATES: readonly { value: string; label: string }[] = [
  { value: "", label: "Not set yet" },
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
];

/** What the panel has to say about the project that now exists. */
interface CreatedProject {
  id: string;
  name: string;
}

/**
 * Create a project — name, purpose, state and the strings its evidence arrives
 * on, in one pass.
 *
 * A disclosure rather than a dialog, for the same reason the team page's invite
 * is: two to four fields do not justify an overlay, a focus trap and an inert
 * background, and the portfolio behind this panel is the context the creator is
 * working from rather than something to blank out.
 *
 * **Source strings belong here rather than later, because they are what makes a
 * project real.** Evidence reaches a project by resolving a citation string
 * against a claim, so a project created without one is a name nothing will ever
 * arrive at — which is exactly the "Not set up yet" tile the portfolio filled
 * with when this form asked for a name and a purpose and nothing else.
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
  const stateId = useId();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [declaredState, setDeclaredState] = useState("");
  const [chosen, setChosen] = useState<readonly string[]>([]);
  const [typedSource, setTypedSource] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [created, setCreated] = useState<CreatedProject | null>(null);

  /*
   * Suggestions come from the facets, which are the strings CAIRN has actually
   * seen on evidence — never a list of what it could hold. Offering a
   * repository nothing was ever recorded against would invite a claim that can
   * only ever stay empty.
   */
  const loadSuggestions = useCallback(
    (signal: AbortSignal): Promise<Facets> => client.getFacets(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state: facets } = useAsync(loadSuggestions, "load the source strings CAIRN has seen");
  const suggestions = facets.status === "ready" ? (facets.data.projects ?? []) : [];

  function reset(): void {
    setName("");
    setPurpose("");
    setDeclaredState("");
    setChosen([]);
    setTypedSource("");
  }

  function toggle(value: string): void {
    setChosen((current) =>
      current.includes(value) ? current.filter((held) => held !== value) : [...current, value],
    );
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setProblem(null);
    setCreated(null);
    setSaving(true);

    const typed = typedSource.trim();
    // Through a Set, because a creator can tick a suggestion and then type the
    // same string: sending it twice is one claim asked for twice.
    const sourceStrings = [...new Set(typed === "" ? chosen : [...chosen, typed])];
    // Captured before the form is cleared, so the follow-up call below still
    // knows what was chosen.
    const wanted = declaredState;

    let project: ProjectDetail;
    try {
      project = await client.createProject(workspaceId, {
        name,
        // Spread rather than sending an empty string: `exactOptionalPropertyTypes`
        // aside, a blank purpose is an absent one, not a purpose that is "".
        ...(purpose.trim() === "" ? {} : { purpose }),
        ...(sourceStrings.length === 0 ? {} : { sourceStrings }),
      });
    } catch (error: unknown) {
      // The typed values are deliberately left alone: a conflict is something
      // to adjust, and clearing the form would make somebody retype four fields
      // to change one of them.
      setProblem(describeCreateFailure(error));
      setSaving(false);
      return;
    }

    // The project exists from here on, and every branch below has to say so.
    setCreated({ id: project.id, name: project.name });
    reset();
    onCreated();

    /*
     * The state is a second call because `createProject` takes none — the API
     * stamps a declaration with who made it, and it only learns that from the
     * PATCH. Sent only when somebody actually chose one: "Not set yet" means no
     * request at all, rather than a request declaring nothing.
     */
    if (wanted !== "") {
      try {
        await client.updateProject(workspaceId, project.id, { state: wanted });
      } catch (error: unknown) {
        // Precisely what happened, never a blanket failure: the project is real
        // and is in the portfolio behind this panel, and telling the creator
        // that creation failed would send them to make it a second time.
        setProblem(partialFailure(error));
      }
    }

    setSaving(false);
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

          <div className={styles.control}>
            <label className={styles.controlLabel} htmlFor={stateId}>
              State
            </label>
            <select
              className={styles.select}
              id={stateId}
              value={declaredState}
              disabled={saving}
              onChange={(event) => {
                setDeclaredState(event.target.value);
              }}
            >
              {NEW_PROJECT_STATES.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </select>
            <p className={styles.createHint}>
              A state is recorded as your declaration, never inferred. Leave it unset until somebody
              has decided.
            </p>
          </div>

          <fieldset className={styles.sources}>
            <legend className={styles.sourcesLegend}>Source strings</legend>
            <p className={styles.createHint}>
              A repository or channel name as it appears on evidence.
            </p>

            {facets.status === "loading" && (
              <p className={styles.createHint}>Looking for the strings CAIRN has already seen.</p>
            )}

            {/*
              The suggestions failing is not the form failing. It costs the
              reader a list they could have ticked; the input below still claims
              any string they can type, so the panel says what is missing in one
              line and carries on.
            */}
            {facets.status === "failed" && (
              <p className={styles.createHint}>
                Suggestions are unavailable right now. You can still type a source string below.
              </p>
            )}

            {facets.status === "ready" && suggestions.length === 0 && (
              <p className={styles.createHint}>
                CAIRN has not seen any source strings in this workspace yet.
              </p>
            )}

            {suggestions.length > 0 && (
              <ul className={styles.sourceList}>
                {suggestions.map((value) => (
                  <li key={value}>
                    <label className={styles.sourceOption}>
                      <input
                        type="checkbox"
                        className={styles.checkbox}
                        checked={chosen.includes(value)}
                        disabled={saving}
                        onChange={() => {
                          toggle(value);
                        }}
                      />
                      {/* Verbatim and monospaced: a machine will match this
                        character for character, and a proportional face makes
                        it look like prose that has been paraphrased. */}
                      <span className={styles.sourceValue}>{value}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}

            <Field
              label="Another source string"
              hint="For one CAIRN has not seen yet. Optional."
              maxLength={200}
              value={typedSource}
              disabled={saving}
              onChange={(event) => {
                setTypedSource(event.target.value);
              }}
            />
          </fieldset>

          <Button type="submit" variant="primary" loading={saving}>
            Create project
          </Button>
          {problem !== null && <InlineProblem error={problem} />}
        </form>
      )}

      {created !== null && (
        <div className={styles.createDone}>
          <StatusNote>{`${created.name} was created.`}</StatusNote>
          {/* Straight into the project, because adding people is the next thing
            somebody wants and it lives there rather than here. */}
          <Link className={utility.actionLink} href={`/projects/${created.id}`}>
            {`Open ${created.name} to add people`}
          </Link>
        </div>
      )}
    </Card>
  );
}

/**
 * A refused creation, said as the thing that was refused.
 *
 * A 409 here is one of exactly two conflicts and they ask different things of
 * the reader: a name somebody already used, or a source string another project
 * already claims. The generic copy's "Trying again may work" is false for both.
 */
function describeCreateFailure(error: unknown): DescribedError {
  if (error instanceof ApiError && error.status === 409) {
    const message = error.is("source-string-claimed")
      ? "Another project in this workspace already claims one of those source strings. A string belongs to one project at a time, so this will not start working on its own — release it on that project first, or choose a different string."
      : error.is("project-name-taken")
        ? "A project in this workspace already has that name. Choose a different name."
        : "That name, or one of those source strings, is already taken in this workspace.";

    const described: DescribedError = { message };
    // Assigned only when present: `exactOptionalPropertyTypes` is on.
    if (error.problem.requestId !== undefined) described.requestId = error.problem.requestId;
    return described;
  }

  return describeError(error, "create this project");
}

/** The project was created and the declaration was not. Both halves get said,
 * because only one of them is something to do again. */
function partialFailure(error: unknown): DescribedError {
  const described = describeError(error, "set the state on this project");
  const partial: DescribedError = {
    message: `The project was created, but the state could not be set. ${described.message} You can declare it on the project's own page.`,
  };
  if (described.requestId !== undefined) partial.requestId = described.requestId;
  return partial;
}

function projectsLabel(total: number, selected: string): string {
  const noun = total === 1 ? "project" : "projects";
  const count = String(total);
  return selected === "" ? `${count} ${noun}` : `${count} ${noun} in this state`;
}
