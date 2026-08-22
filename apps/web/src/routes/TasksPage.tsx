"use client";

import {
  ApiError,
  type ProjectDetail,
  type TaskCreateBody,
  type TaskList,
  type TaskSummary,
} from "@cairn/api-client";
import { Button } from "@cairn/ui";
import clsx from "clsx";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Avatar } from "../components/Avatar.js";
import { Card } from "../components/Card.js";
import { formatDay } from "../components/dates.js";
import { Field } from "../components/Field.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { PageHeader } from "../components/PageHeader.js";
import { QuickAddTask, type QuickAddTarget } from "../components/QuickAddTask.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./TasksPage.module.css";

/**
 * The owner's board: every task across the workspace, in columns ordered by
 * what the owner does about them — hand out, watch, approve, remember.
 *
 * The person running a workspace assigns work rather than holding it, so a
 * screen scoped to "the tasks assigned to you" was empty exactly when it was
 * opened by the person the route belongs to. This board answers their real
 * questions instead: Assign leads because handing work to somebody is the one
 * action this screen exists for, and Test carries the approve/send-back pair
 * because the owner is the second pair of eyes the review handoff asks for.
 *
 * **No counts anywhere, deliberately** — a column header is "Assign", never
 * "Assign (4)": a number over a column of work is a backlog figure, and a
 * backlog figure beside names is the first step towards a scoreboard.
 */
export function TasksPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader
          title="Tasks"
          description="Assign work, approve reviews, and see what the team finished."
        />
        <EmptyState title="Join a workspace to see its tasks">
          Join a workspace and the tasks across its projects appear here.
        </EmptyState>
      </>
    );
  }

  return <WorkspaceTasks workspaceId={activeWorkspace.id} />;
}

/**
 * How many projects are examined to collect the workspace's tasks.
 *
 * BACKEND GAP: there is no endpoint that returns every task in a workspace,
 * so this screen reads the portfolio and then each project's board. Bounded,
 * because the cost is two requests per project — the same cap, for the same
 * reason, as the Team page's role fan-out. When an endpoint lands, this
 * fan-out and its cap go with it.
 */
const PROJECTS_EXAMINED = 20;

/** Priority as a word, plainly. A value the client does not recognise renders
 * as its own text. */
const PRIORITY_LABEL: Readonly<Record<string, string>> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

/** The four priorities the form offers, led by the default. */
const PRIORITY_CHOICES: readonly { value: string; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

/** Somebody a task can be handed to: a current member of its project. */
interface AssignableMember {
  personId: string;
  displayName: string;
}

/** One project, with its board and the people work on it can go to. */
interface ProjectSection {
  id: string;
  name: string;
  tasks: TaskSummary[];
  members: AssignableMember[];
}

/** One project as the tab row lists it — every project in the portfolio,
 * whether or not its board could be read. */
interface ProjectTab {
  id: string;
  name: string;
  /** False when this project's reads failed. Its tab still stands: a project
   * that could not be read must never look like a project with no work. */
  readable: boolean;
}

interface WorkspaceTasksData {
  /** Every project, in portfolio order — the tab row's contents. */
  projects: ProjectTab[];
  sections: ProjectSection[];
  /** The projects whose reads failed, named so the note below can say exactly
   * what is missing while everything else stays on screen. */
  unreadable: ProjectTab[];
}

/** One task on the board, carrying the project context its card needs. */
interface BoardEntry {
  task: TaskSummary;
  projectId: string;
  projectName: string;
  members: AssignableMember[];
}

function WorkspaceTasks({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const { activeRole } = useAuth();
  const panelId = useId();
  const [creating, setCreating] = useState(false);
  /*
   * Which project's board is on screen — "" for all of them.
   *
   * Component state rather than a search parameter, deliberately: reading the
   * URL here needs `useSearchParams`, which this codebase must wrap in a
   * Suspense boundary and which has broken the production build before. A tab
   * selection is a view preference within one visit, not an address somebody
   * sends to a colleague, so it costs nothing to keep it here.
   */
  const [selected, setSelected] = useState("");
  /*
   * Which column's quick composer stands open — one across the whole board, or
   * null. Held here rather than in the board below because a create re-reads
   * the workspace, and the board is unmounted while that read is in flight: a
   * composer that owned its own open flag would close itself every time it
   * succeeded, which is the opposite of what adding several in a row needs.
   */
  const [openColumn, setOpenColumn] = useState<string | null>(null);

  const load = useCallback(
    async (signal: AbortSignal): Promise<WorkspaceTasksData> => {
      const options = { signal };
      const portfolio = await client.listProjects(workspaceId, undefined, options);
      const projects = (portfolio.projects ?? []).slice(0, PROJECTS_EXAMINED);

      // Settled, not all: one project's board failing to read must cost the
      // reader that project's cards and a one-line note — never the page.
      const settled = await Promise.allSettled(
        projects.map(async (project): Promise<ProjectSection> => {
          const [tasks, detail]: [TaskList, ProjectDetail] = await Promise.all([
            client.listTasks(workspaceId, project.id, undefined, options),
            client.getProject(workspaceId, project.id, options),
          ]);
          return {
            id: project.id,
            name: project.name,
            tasks: tasks.tasks ?? [],
            members: (detail.members ?? [])
              // A closed membership is history: work cannot be handed there.
              .filter((membership) => membership.removedAt == null)
              .map((membership) => ({
                personId: membership.personId,
                displayName: membership.displayName,
              })),
          };
        }),
      );

      const tabs: ProjectTab[] = [];
      const sections: ProjectSection[] = [];
      const unreadable: ProjectTab[] = [];
      settled.forEach((result, index) => {
        const project = projects[index];
        if (project === undefined) return;
        const readable = result.status === "fulfilled";
        const tab: ProjectTab = { id: project.id, name: project.name, readable };
        tabs.push(tab);
        if (result.status === "fulfilled") sections.push(result.value);
        else unreadable.push(tab);
      });

      return { projects: tabs, sections, unreadable };
    },
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the tasks in this workspace");

  // Decides what to *offer*, never what to allow: the API holds the permission
  // and refuses a request this screen was wrong to show. Viewers read; they
  // are not offered a control that would be refused.
  const canAct = activeRole === "owner" || activeRole === "admin" || activeRole === "member";
  const canCreate = canAct && state.status === "ready" && state.data.sections.length > 0;

  return (
    <>
      <PageHeader
        title="Tasks"
        description="Assign work, approve reviews, and see what the team finished."
        actions={
          canCreate ? (
            <Button
              type="button"
              variant={creating ? "secondary" : "primary"}
              aria-expanded={creating}
              aria-controls={panelId}
              onClick={() => {
                setCreating(!creating);
              }}
            >
              {creating ? "Cancel" : "New task"}
            </Button>
          ) : undefined
        }
      />

      {canCreate && creating && (
        <NewTask
          workspaceId={workspaceId}
          panelId={panelId}
          sections={state.data.sections}
          defaultProject={selected}
          onCreated={() => {
            setCreating(false);
            reload();
          }}
        />
      )}

      {state.status === "loading" && (
        <LoadingState label="the tasks in this workspace" shape="rows" lines={4} />
      )}

      {state.status === "failed" && (
        <ErrorState title="The tasks could not be loaded" error={state.error} onRetry={reload} />
      )}

      {state.status === "ready" && (
        <Board
          workspaceId={workspaceId}
          data={state.data}
          selected={selected}
          onSelect={(projectId) => {
            // A composer belongs to the view it was opened in: the project it
            // would create into has just changed under it.
            setOpenColumn(null);
            setSelected(projectId);
          }}
          canAct={canAct}
          openColumn={openColumn}
          onOpenColumn={setOpenColumn}
          onChanged={reload}
        />
      )}
    </>
  );
}

/** What a column offers on its cards, beyond reading them. */
type ColumnAction = "assign" | "review" | "none";

/**
 * The five columns, in the order the owner works them. A column that stands
 * empty still stands — a board with missing columns reads as a broken board —
 * and the two the owner checks for good news say it in their own words.
 */
const COLUMNS: readonly {
  key: string;
  title: string;
  action: ColumnAction;
  empty: string;
  /** The state the column's quick composer creates into — the column a reader
   * adds work at the foot of is the column that work lands in. */
  createState: string;
  /** False for Assign, which *is* the column for work nobody holds yet: its
   * composer hides the assignee select and creates with no assignee. */
  canAssign: boolean;
}[] = [
  {
    key: "assign",
    title: "Assign",
    action: "assign",
    empty: "Everything is assigned.",
    createState: "todo",
    canAssign: false,
  },
  {
    key: "todo",
    title: "To do",
    action: "none",
    empty: "Nothing here.",
    createState: "todo",
    canAssign: true,
  },
  {
    key: "inProgress",
    title: "In progress",
    action: "none",
    empty: "Nothing here.",
    createState: "in_progress",
    canAssign: true,
  },
  {
    key: "test",
    title: "Test",
    action: "review",
    empty: "Nothing is waiting for review.",
    createState: "in_review",
    canAssign: true,
  },
  {
    key: "completed",
    title: "Completed",
    action: "none",
    empty: "Nothing here.",
    createState: "done",
    canAssign: true,
  },
];

function Board({
  workspaceId,
  data,
  selected,
  onSelect,
  canAct,
  openColumn,
  onOpenColumn,
  onChanged,
}: {
  workspaceId: string;
  data: WorkspaceTasksData;
  /** The chosen project's id, or "" for every project pooled. */
  selected: string;
  onSelect: (projectId: string) => void;
  canAct: boolean;
  /** The one column whose quick composer stands open, or null. */
  openColumn: string | null;
  onOpenColumn: (columnKey: string | null) => void;
  onChanged: () => void;
}): ReactNode {
  if (data.sections.length === 0 && data.unreadable.length === 0) {
    return (
      <EmptyState
        title="No projects yet"
        action={
          <Link className={utility.actionLink} href="/projects">
            Go to projects
          </Link>
        }
      >
        Tasks live on a project. Create a project first, and its work appears here.
      </EmptyState>
    );
  }

  // Flat, in the order projects and their boards were returned — creation
  // order within a project, which measures nothing about anyone. There is no
  // completion timestamp on a summary, so Completed keeps this order too.
  const pooled: BoardEntry[] = data.sections.flatMap((section) =>
    section.tasks.map((task) => ({
      task,
      projectId: section.id,
      projectName: section.name,
      members: section.members,
    })),
  );

  const chosen = data.projects.find((project) => project.id === selected) ?? null;
  // An unknown id — a project that has gone since the tabs were drawn — falls
  // back to every project rather than to a board that is empty for no stated
  // reason.
  const scope = chosen === null ? "" : chosen.id;
  const all = scope === "" ? pooled : pooled.filter((entry) => entry.projectId === scope);
  // The tab already names the project, so the cards stop repeating it.
  const showProject = scope === "";

  // Assign owns every unassigned, unfinished task, whatever its state — that
  // is the column's whole point. The state columns carry the rest, so no card
  // appears twice: a card shown in two columns reads as two tasks.
  const unfinished = (entry: BoardEntry): boolean =>
    entry.task.assigneePersonId == null && entry.task.state !== "done";
  const inState = (entry: BoardEntry, states: readonly string[]): boolean =>
    !unfinished(entry) && states.includes(entry.task.state);

  const byColumn: Readonly<Record<string, BoardEntry[]>> = {
    assign: all.filter(unfinished),
    todo: all.filter((entry) => inState(entry, ["todo"])),
    // Blocked work is in-progress work that stopped; the card says so with a
    // pill rather than a sixth column pushing it off-screen.
    inProgress: all.filter((entry) => inState(entry, ["in_progress", "blocked"])),
    test: all.filter((entry) => inState(entry, ["in_review"])),
    completed: all.filter((entry) => entry.task.state === "done"),
  };

  // Only the projects the current view actually covers: naming a project the
  // reader is not looking at would be a note about somewhere else.
  const missing = scope === "" ? data.unreadable : data.unreadable.filter((p) => p.id === scope);
  const scopeUnreadable = chosen !== null && !chosen.readable;

  /*
   * Where each column's quick composer creates.
   *
   * On a single project tab the composer already knows the project and its
   * members, so it shows no project control. Pooled, it has to ask: a column
   * spanning every project cannot guess which one a new task belongs to.
   */
  const scopeSection = data.sections.find((section) => section.id === scope) ?? null;
  const target: QuickAddTarget =
    scopeSection === null
      ? { kind: "choose", projects: data.sections }
      : { kind: "fixed", projectId: scopeSection.id, members: scopeSection.members };
  // Nothing to create into is not a control worth offering.
  const canAdd = canAct && data.sections.length > 0;

  return (
    <div className={styles.boardArea}>
      <ProjectTabs projects={data.projects} selected={scope} onSelect={onSelect} />

      {missing.length > 0 && (
        <div className={styles.unreadable}>
          {/* One line, not a panel: the rest of the board is real and stays. */}
          <p className={styles.unreadableNote}>
            {`Tasks in ${listNames(missing.map((project) => project.name))} could not be read right now.`}
          </p>
          <Button size="sm" onClick={onChanged}>
            Try again
          </Button>
        </div>
      )}

      {/*
        A board of five empty columns would tell this reader that the project
        they just chose has no work, when the truth is that CAIRN could not
        read it. The note above says which it is; the columns stay away until
        there is something true to put in them.
      */}
      {!scopeUnreadable && (
        <div
          className={styles.board}
          role="group"
          aria-label={chosen === null ? "Tasks in every project" : `Tasks in ${chosen.name}`}
        >
          {COLUMNS.map((column) => (
            <Column
              key={column.key}
              title={column.title}
              empty={column.empty}
              action={column.action}
              muted={column.key === "completed"}
              entries={byColumn[column.key] ?? []}
              showProject={showProject}
              workspaceId={workspaceId}
              canAct={canAct}
              canAdd={canAdd}
              createState={column.createState}
              canAssign={column.canAssign}
              target={target}
              composerOpen={openColumn === column.key}
              onOpenComposer={() => {
                onOpenColumn(column.key);
              }}
              onCloseComposer={() => {
                onOpenColumn(null);
              }}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The project switcher: every project, plus the pooled view, as one row.
 *
 * A button group with `aria-current` rather than an ARIA tablist, and that is
 * a deliberate choice between two correct options. A real tablist takes on
 * obligations — roving tabindex, arrow-key navigation, one focusable tab, a
 * panel wired by `aria-controls` — and a half-built one is worse for a
 * keyboard user than no tablist at all, because their arrow keys stop doing
 * what the role promised. Plain buttons are natively reachable and operable
 * with Tab and Enter, `aria-current="true"` puts the selection in the
 * accessibility tree where the monochrome fill alone could not carry it, and
 * the board below names the project it is showing.
 *
 * A project whose board could not be read keeps its button. Dropping it would
 * make a failure look like a project that no longer exists.
 */
function ProjectTabs({
  projects,
  selected,
  onSelect,
}: {
  projects: ProjectTab[];
  selected: string;
  onSelect: (projectId: string) => void;
}): ReactNode {
  return (
    <div className={styles.tabs} role="group" aria-label="Show one project">
      <div className={styles.tabRow}>
        {/* The pooled view leads, and is where the screen starts: an owner
          opens this page to see everything, then narrows. */}
        <ProjectTab label="All projects" value="" selected={selected} onSelect={onSelect} />
        {projects.map((project) => (
          <ProjectTab
            key={project.id}
            label={project.name}
            value={project.id}
            selected={selected}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

function ProjectTab({
  label,
  value,
  selected,
  onSelect,
}: {
  label: string;
  value: string;
  selected: string;
  onSelect: (projectId: string) => void;
}): ReactNode {
  const current = value === selected;

  return (
    <button
      type="button"
      className={styles.tab}
      // Styled through the attribute rather than a class, so the visual state
      // and the accessible one cannot drift apart — the sidebar's reasoning.
      aria-current={current ? "true" : undefined}
      onClick={() => {
        onSelect(value);
      }}
    >
      {/* The project's name and nothing else — never a count beside it. */}
      {label}
    </button>
  );
}

/** "Atlas", "Atlas and Borealis", "Atlas, Borealis and Comet" — names in
 * prose, so the note reads as a sentence rather than a report. */
function listNames(names: string[]): string {
  if (names.length === 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1] ?? ""}`;
}

function Column({
  title,
  empty,
  action,
  muted,
  entries,
  showProject,
  workspaceId,
  canAct,
  canAdd,
  createState,
  canAssign,
  target,
  composerOpen,
  onOpenComposer,
  onCloseComposer,
  onChanged,
}: {
  title: string;
  empty: string;
  action: ColumnAction;
  muted: boolean;
  entries: BoardEntry[];
  /** False in the single-project view, where the tab already says it. */
  showProject: boolean;
  workspaceId: string;
  canAct: boolean;
  /** Whether this reader is offered the quick composer at all. */
  canAdd: boolean;
  createState: string;
  canAssign: boolean;
  target: QuickAddTarget;
  composerOpen: boolean;
  onOpenComposer: () => void;
  onCloseComposer: () => void;
  onChanged: () => void;
}): ReactNode {
  const headingId = useId();

  return (
    // A named region per column, so "Assign" is a place a screen reader can
    // land rather than a heading floating over an unlabelled list.
    <section className={styles.column} aria-labelledby={headingId}>
      {/* The plain column name — never a count. */}
      <h2 className={styles.columnTitle} id={headingId}>
        {title}
      </h2>
      {entries.length === 0 ? (
        // An empty column is a fact, said once and quietly — never a zero.
        <p className={styles.columnEmpty}>{empty}</p>
      ) : (
        <ul className={styles.columnList}>
          {entries.map((entry) => (
            <li key={entry.task.id}>
              <BoardCard
                entry={entry}
                action={action}
                muted={muted}
                showProject={showProject}
                workspaceId={workspaceId}
                canAct={canAct}
                onChanged={onChanged}
              />
            </li>
          ))}
        </ul>
      )}

      {/* At the foot, under the work: you add where you are looking. Viewers
        are offered nothing here — the same gating as the card controls. */}
      {canAdd && (
        <QuickAddTask
          workspaceId={workspaceId}
          columnLabel={title}
          state={createState}
          target={target}
          canAssign={canAssign}
          open={composerOpen}
          onOpen={onOpenComposer}
          onClose={onCloseComposer}
          onCreated={onChanged}
        />
      )}
    </section>
  );
}

/**
 * One task on the owner's board, in the project board's visual voice: title,
 * where it lives, who holds it, priority, due — and nothing measured.
 *
 * Local rather than `TaskCard`, because that card stretches its title link
 * over the whole surface, and a card that carries a select or two buttons
 * cannot: the stretched link would sit over the controls. No state badge —
 * the column says the state; the one exception is "Blocked", which rides in
 * the In progress column and says so with a pill.
 */
function BoardCard({
  entry,
  action,
  muted,
  showProject,
  workspaceId,
  canAct,
  onChanged,
}: {
  entry: BoardEntry;
  action: ColumnAction;
  muted: boolean;
  showProject: boolean;
  workspaceId: string;
  canAct: boolean;
  onChanged: () => void;
}): ReactNode {
  const { task } = entry;
  const assigneeName = task.assigneeName ?? null;

  return (
    <article className={clsx(styles.card, muted && styles.cardMuted)}>
      <div className={styles.cardPills}>
        {/* A small mono pill, following StateBadge: weight and border carry
          the priority, colour never does — an "urgent" in red would be the
          first colour on the page and would read as a verdict. */}
        <span
          className={styles.priority}
          aria-label={`Priority: ${PRIORITY_LABEL[task.priority] ?? task.priority}`}
        >
          {PRIORITY_LABEL[task.priority] ?? task.priority}
        </span>
        {task.state === "blocked" && (
          <span className={styles.blocked} aria-label="Task state: Blocked">
            Blocked
          </span>
        )}
      </div>

      <p className={styles.cardTitle}>
        <Link className={styles.cardLink} href={`/tasks/${task.id}`}>
          {task.title}
        </Link>
      </p>

      {/* Dropped in the single-project view: the selected tab already says
        which project this is, and repeating it on every card is noise. */}
      {showProject && (
        <Link className={styles.projectLink} href={`/projects/${entry.projectId}`}>
          {entry.projectName}
        </Link>
      )}

      <div className={styles.cardFoot}>
        {task.assigneePersonId == null ? (
          action === "assign" && canAct ? (
            <AssignControl workspaceId={workspaceId} entry={entry} onAssigned={onChanged} />
          ) : (
            // Unassigned is a fact about the task, not a gap to nag about.
            <span className={styles.unassigned}>Unassigned</span>
          )
        ) : (
          <span className={styles.assignee}>
            <Avatar name={assigneeName ?? "Someone"} size="sm" />
            {assigneeName ?? "Someone"}
          </span>
        )}
        {task.dueOn != null && (
          <time className={styles.due} dateTime={task.dueOn}>
            {`Due ${formatDay(task.dueOn)}`}
          </time>
        )}
      </div>

      {action === "review" && canAct && (
        <ReviewActions workspaceId={workspaceId} entry={entry} onMoved={onChanged} />
      )}
    </article>
  );
}

/**
 * Hand a task to somebody, on the card.
 *
 * A select rather than a dialog: choosing a name is the entire action. The
 * control disables while the request is in flight, and the card's truth comes
 * back from a re-read rather than being patched on screen — the server owns
 * who holds a task. A refusal is said beside the control that caused it.
 */
function AssignControl({
  workspaceId,
  entry,
  onAssigned,
}: {
  workspaceId: string;
  entry: BoardEntry;
  onAssigned: () => void;
}): ReactNode {
  const client = useApiClient();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  function assign(personId: string): void {
    if (personId === "") return;
    setBusy(true);
    setProblem(null);

    client
      .updateTask(workspaceId, entry.task.id, { assigneePersonId: personId })
      .then(() => {
        // Re-read rather than patch: the server owns who holds the task, and
        // the reload also moves the card out of the Assign column.
        onAssigned();
      })
      .catch((error: unknown) => {
        setProblem(describeError(error, "assign this task"));
        setBusy(false);
      });
  }

  return (
    <span className={styles.assignControl}>
      <select
        className={styles.select}
        aria-label={`Assign ${entry.task.title}`}
        value=""
        disabled={busy}
        onChange={(event) => {
          assign(event.target.value);
        }}
      >
        <option value="">Assign to…</option>
        {entry.members.map((member) => (
          <option key={member.personId} value={member.personId}>
            {member.displayName}
          </option>
        ))}
      </select>
      {problem !== null && <InlineProblem error={problem} />}
    </span>
  );
}

/**
 * The review handoff, worked from the reviewer's side: approve it as done, or
 * send it back for another pass.
 *
 * The API's rule is that the person who sent a task to review cannot also
 * approve it. The owner usually did not, so this is the second pair of eyes
 * the rule asks for — and when the owner *did* send it, the API refuses with
 * a sentence written for exactly that case, which is surfaced verbatim rather
 * than paraphrased into something vaguer.
 */
function ReviewActions({
  workspaceId,
  entry,
  onMoved,
}: {
  workspaceId: string;
  entry: BoardEntry;
  onMoved: () => void;
}): ReactNode {
  const client = useApiClient();
  const [busy, setBusy] = useState<"done" | "back" | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  function move(to: "done" | "in_progress"): void {
    setBusy(to === "done" ? "done" : "back");
    setProblem(null);

    client
      .setTaskState(workspaceId, entry.task.id, to)
      .then(() => {
        // Re-read rather than patch: the server owns the workflow, and the
        // reload also moves the card into the column it now belongs to.
        onMoved();
      })
      .catch((error: unknown) => {
        setProblem(describeReviewRefusal(error));
        setBusy(null);
      });
  }

  return (
    <span className={styles.reviewActions}>
      <span className={styles.reviewButtons}>
        <Button
          size="sm"
          variant="primary"
          loading={busy === "done"}
          disabled={busy === "back"}
          aria-label={`Mark ${entry.task.title} done`}
          onClick={() => {
            move("done");
          }}
        >
          Mark done
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={busy === "back"}
          disabled={busy === "done"}
          aria-label={`Send ${entry.task.title} back`}
          onClick={() => {
            move("in_progress");
          }}
        >
          Send back
        </Button>
      </span>
      {problem !== null && <InlineProblem error={problem} />}
    </span>
  );
}

/**
 * A refused review move, said in the API's own words when it has them.
 *
 * A 409 here is the review-handoff rule: whoever sent a task to review cannot
 * also approve it. The server's sentence names that rule precisely, so it is
 * shown verbatim — paraphrasing it into the generic "trying again may work"
 * would be false, because it will be refused identically forever.
 */
function describeReviewRefusal(error: unknown): DescribedError {
  if (error instanceof ApiError && error.status === 409 && error.problem.detail !== "") {
    const described: DescribedError = { message: error.problem.detail };
    // Assigned only when present: `exactOptionalPropertyTypes` is on.
    if (error.problem.requestId !== undefined) described.requestId = error.problem.requestId;
    return described;
  }
  return describeError(error, "move this task");
}

/**
 * Create a task on any project — a disclosure under the header's toggle,
 * following the portfolio's NewProject panel: five fields do not justify a
 * dialog, a focus trap and an inert background, and the board behind this
 * panel is the context the creator is working from. The assignee choice
 * follows the chosen project, because a task can only be handed to a member
 * of its own project.
 */
function NewTask({
  workspaceId,
  panelId,
  sections,
  defaultProject,
  onCreated,
}: {
  workspaceId: string;
  /** Named by the header's toggle button via `aria-controls`. */
  panelId: string;
  sections: ProjectSection[];
  /** The project the board is showing, or "" for the pooled view. Chosen for
   * the creator rather than asked of them again — and still changeable. */
  defaultProject: string;
  onCreated: () => void;
}): ReactNode {
  const client = useApiClient();
  const projectId = useId();
  const priorityId = useId();
  const assigneeId = useId();
  const descriptionId = useId();
  const [project, setProject] = useState(defaultProject);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("normal");
  const [assignee, setAssignee] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const chosenProject = sections.find((section) => section.id === project) ?? null;

  function reset(): void {
    setProject(defaultProject);
    setTitle("");
    setDescription("");
    setPriority("normal");
    setAssignee("");
    setDueOn("");
  }

  const submit = (event: SyntheticEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (project === "") return;
    setProblem(null);
    setSaving(true);

    const body: TaskCreateBody = {
      title,
      description: description.trim(),
      priority,
      // This form creates ordinary work, so it opens in the first column. The
      // columns' own "+ Add task" composers are what create straight into a
      // later state; this panel exists for the fields they deliberately omit —
      // description and due date.
      state: "todo",
      // Spread rather than sending an empty string: an unassigned task has no
      // assignee, not an assignee called "".
      ...(assignee === "" ? {} : { assigneePersonId: assignee }),
      ...(dueOn === "" ? {} : { dueOn }),
    };

    client
      .createTask(workspaceId, project, body)
      .then(() => {
        reset();
        // Re-read rather than patch the copy on screen: the server owns each
        // board's order and the task's stamped fields. The caller collapses
        // the panel.
        onCreated();
      })
      .catch((error: unknown) => {
        // The typed values are deliberately left alone: a refusal is something
        // to adjust, not a reason to retype five fields.
        setProblem(describeError(error, "create this task"));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  return (
    <Card className={styles.create}>
      <div className={styles.createHead}>
        <h2 className={styles.createTitle}>New task</h2>
        <p className={styles.createNote}>A project and a title are the only requirements.</p>
      </div>

      <form className={styles.createForm} id={panelId} onSubmit={submit}>
        <div className={styles.control}>
          <label className={styles.label} htmlFor={projectId}>
            Project
          </label>
          <select
            className={styles.select}
            id={projectId}
            required
            value={project}
            onChange={(event) => {
              setProject(event.target.value);
              // The old choice may not be a member of the new project.
              setAssignee("");
            }}
          >
            <option value="">Choose a project</option>
            {sections.map((section) => (
              <option key={section.id} value={section.id}>
                {section.name}
              </option>
            ))}
          </select>
        </div>

        <Field
          label="Title"
          required
          maxLength={200}
          value={title}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />

        <div className={styles.control}>
          <label className={styles.label} htmlFor={descriptionId}>
            Description
          </label>
          <textarea
            className={styles.textarea}
            id={descriptionId}
            rows={3}
            maxLength={2000}
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
          <p className={styles.hint}>What done looks like, in a sentence or two. Optional.</p>
        </div>

        <div className={styles.control}>
          <label className={styles.label} htmlFor={priorityId}>
            Priority
          </label>
          <select
            className={styles.select}
            id={priorityId}
            value={priority}
            onChange={(event) => {
              setPriority(event.target.value);
            }}
          >
            {PRIORITY_CHOICES.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.control}>
          <label className={styles.label} htmlFor={assigneeId}>
            Assignee
          </label>
          <select
            className={styles.select}
            id={assigneeId}
            value={assignee}
            disabled={chosenProject === null}
            onChange={(event) => {
              setAssignee(event.target.value);
            }}
          >
            {/* The honest default: a task nobody holds yet is a true
              statement, not a gap the form should fill in. */}
            <option value="">Nobody yet</option>
            {(chosenProject?.members ?? []).map((member) => (
              <option key={member.personId} value={member.personId}>
                {member.displayName}
              </option>
            ))}
          </select>
          <p className={styles.hint}>Members of the chosen project. Optional.</p>
        </div>

        <Field
          label="Due date"
          type="date"
          hint="Optional."
          value={dueOn}
          onChange={(event) => {
            setDueOn(event.target.value);
          }}
        />

        <Button type="submit" variant="primary" loading={saving}>
          Create task
        </Button>
        {problem !== null && <InlineProblem error={problem} />}
      </form>
    </Card>
  );
}
