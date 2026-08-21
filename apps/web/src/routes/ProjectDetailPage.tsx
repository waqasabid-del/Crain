"use client";

import type { CairnClient, ProjectDetail } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { Avatar } from "../components/Avatar.js";
import { Card } from "../components/Card.js";
import { Field } from "../components/Field.js";
import { InlineProblem } from "../components/InlineProblem.js";
import { PageHeader } from "../components/PageHeader.js";
import { StateBadge } from "../components/StateBadge.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { StatusNote } from "../components/StatusNote.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./ProjectDetailPage.module.css";

/**
 * One project: what it is, who is part of it, and what the sources recorded.
 *
 * **The Work section is the API's own groups, flattened.** Delivered work,
 * decisions, blockers and open questions come back pre-grouped and cited; the
 * page interleaves them into one newest-first wall of tiles and labels each
 * tile with the group it came from. It is deliberately called Work and never
 * "Tasks": CAIRN has no task model, and a heading that implies one turns
 * evidence somebody can check into a backlog somebody is answerable for.
 *
 * **Planned work is one honest line, not a section.** CAIRN holds no
 * planned-work model — no task, no assignment, no estimate exists in the data —
 * so a "remaining" figure would be invented. The page says so in a sentence and
 * gives the absence no further room.
 *
 * **Membership is context.** The Team grid says who is part of the project and
 * what they would call their own role here — never what they produced, never a
 * count, never a comparison. Removed members stay visible as closed history,
 * because a shrinking list that silently drops people reads as a project that
 * never had them.
 */
export function ProjectDetailPage({ projectId }: { projectId: string }): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Project" />
        <EmptyState title="Join a workspace to see this project">
          Join a workspace to see this project.
        </EmptyState>
      </>
    );
  }

  return <Detail workspaceId={activeWorkspace.id} projectId={projectId} />;
}

/** One fact in a project's rollup, as the generated client types it. */
type ProjectFact = NonNullable<ProjectDetail["rollup"]["delivered"]>[number];

/** A citation on one of those facts. */
type FactSource = NonNullable<ProjectFact["sources"]>[number];

/** One member row, as the generated client types it. */
type MemberEntry = NonNullable<ProjectDetail["members"]>[number];

/**
 * How many tiles the Work wall shows before it stops.
 *
 * A wall, not a feed: past a screenful the reader is scrolling rather than
 * reading, and the whole stream already has a home at `/feed`.
 */
const WORK_TILES_SHOWN = 12;

/**
 * How many facts the credit lookup reads.
 *
 * BACKEND GAP: a rollup fact carries its statement, its certainty and its
 * citations — but not the person it credits, so the name cannot come from the
 * project payload. Until the rollup carries a mention, the page reads the
 * project's facts once and matches them by statement. It is an enrichment and
 * nothing depends on it: if the read fails the tiles render uncredited rather
 * than the page failing, and no name is ever guessed.
 */
const CREDIT_LOOKUP = 100;

/** The states this form offers. A project already in some other state keeps it
 * as a fourth option — see `stateChoices`. */
const STATE_CHOICES: readonly { value: string; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
];

/** Suggestions, not a taxonomy: the role is whatever somebody would call their
 * own part in this project, so the input stays free text and the datalist only
 * saves typing. */
const ROLE_SUGGESTIONS: readonly string[] = [
  "Frontend",
  "Backend",
  "DevOps",
  "UI/UX Design",
  "QA",
  "Product",
  "Data",
];

/** One tile on the Work wall. */
interface WorkItem {
  key: string;
  /** Which rollup group it came from, in the word the tile shows. */
  kind: string;
  statement: string;
  /** The person the evidence credits, when the lookup found one. */
  credit: string | null;
  /** ISO 8601, or null when the source recorded no time. */
  occurredAt: string | null;
  sources: FactSource[];
}

interface ProjectView {
  project: ProjectDetail;
  /** Statement to credited person. Empty when the lookup did not run. */
  credits: ReadonlyMap<string, string>;
}

function Detail({ workspaceId, projectId }: { workspaceId: string; projectId: string }): ReactNode {
  const client = useApiClient();
  const { activeRole } = useAuth();

  const load = useCallback(
    async (signal: AbortSignal): Promise<ProjectView> => {
      const project = await client.getProject(workspaceId, projectId, { signal });
      return { project, credits: await creditsFor(client, workspaceId, project.name, signal) };
    },
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

  const { project, credits } = state.data;
  const members = project.members ?? [];
  const sources = project.sources ?? [];
  const work = workItems(project, credits);
  const canConfigure = activeRole === "owner" || activeRole === "admin";

  return (
    <div className={styles.stack}>
      {/*
       * The hero card *is* this page's header, so it owns the `<h1>`, exactly
       * as the person page's does. A PageHeader above it would set the project
       * name twice on one screen.
       */}
      <Card className={styles.hero}>
        <div className={styles.heroBand}>
          <div className={styles.heroText}>
            <span className={styles.eyebrow}>Project</span>
            <h1 className={styles.heroName}>{project.name}</h1>

            <div className={styles.heroFacts}>
              <StateBadge state={project.state} />
              {project.archivedAt != null && (
                <span className={styles.archived}>Archived — its evidence still works</span>
              )}
            </div>

            {project.purpose != null && project.purpose !== "" && (
              <p className={styles.purpose}>{project.purpose}</p>
            )}

            <p className={styles.declared}>{declaredBy(project)}</p>

            {sources.length === 0 ? (
              <p className={styles.declared}>
                No sources claimed yet, so no evidence reaches this project.
              </p>
            ) : (
              <ul className={styles.chips} aria-label="Claimed sources">
                {sources.map((source) => (
                  <li className={styles.chip} key={source.value}>
                    {source.value}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <Link className={utility.actionLink} href="/projects">
            All projects
          </Link>
        </div>
      </Card>

      <Card title="Team" description="Who is part of this project.">
        {members.length === 0 ? (
          <EmptyState title="Nobody added yet" headingLevel={3}>
            An owner or admin can add people. Adding someone assigns them no work.
          </EmptyState>
        ) : (
          <ul className={styles.people}>
            {oneRowPerPerson(members).map((member) => (
              <li className={styles.person} key={member.personId}>
                <Avatar name={member.displayName} size="md" />
                <div className={styles.personBody}>
                  <p className={styles.personName}>
                    {/*
                     * Stretched `::after` rather than wrapping the card in the
                     * link: the accessible name of this link stays the person's
                     * name, instead of becoming their name plus their role plus
                     * every other word in the tile.
                     */}
                    <Link className={styles.personLink} href={`/people/${member.personId}`}>
                      {member.displayName}
                    </Link>
                  </p>
                  <div className={styles.personTags}>
                    <span className={styles.personRole}>{member.projectRole ?? "No role set"}</span>
                    {member.removedAt != null && <span className={styles.removed}>Removed</span>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Work" description="What the sources recorded.">
        {work.length === 0 ? (
          <EmptyState title="Nothing recorded yet" headingLevel={3}>
            Nothing recorded under this project yet.
          </EmptyState>
        ) : (
          <>
            <ul className={styles.tiles}>
              {work.slice(0, WORK_TILES_SHOWN).map((item) => (
                <li className={styles.tile} key={item.key}>
                  <span className={styles.tileKind}>{item.kind}</span>
                  <p className={styles.tileStatement}>{item.statement}</p>
                  <div className={styles.tileFoot}>
                    {item.credit != null && <span className={styles.credit}>{item.credit}</span>}
                    {item.sources.map((source) =>
                      source.url == null ? (
                        <span className={styles.source} key={source.evidenceId}>
                          {source.evidenceId}
                        </span>
                      ) : (
                        <a
                          className={styles.source}
                          href={source.url}
                          key={source.evidenceId}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {source.evidenceId}
                        </a>
                      ),
                    )}
                  </div>
                </li>
              ))}
            </ul>
            <Link className={utility.actionLink} href="/feed">
              View all activity
            </Link>
          </>
        )}
        {/* One line, not a section: the absence is worth stating once and is
          not worth a panel of its own. */}
        <p className={styles.caveat}>CAIRN records what your tools report. Planned work is not.</p>
      </Card>

      {canConfigure && (
        <Settings
          workspaceId={workspaceId}
          project={project}
          members={members}
          onChanged={reload}
        />
      )}
    </div>
  );
}

/** Purpose, state and membership — for the roles that may change them. */
function Settings({
  workspaceId,
  project,
  members,
  onChanged,
}: {
  workspaceId: string;
  project: ProjectDetail;
  members: MemberEntry[];
  onChanged: () => void;
}): ReactNode {
  const current = members.filter((member) => member.removedAt == null);

  return (
    <Card title="Project settings" description="Purpose, state and who is here.">
      <div className={styles.settings}>
        <EditProject workspaceId={workspaceId} project={project} onChanged={onChanged} />
        <AddMember
          workspaceId={workspaceId}
          projectId={project.id}
          current={current}
          onChanged={onChanged}
        />
        <CurrentMembers
          workspaceId={workspaceId}
          projectId={project.id}
          current={current}
          onChanged={onChanged}
        />
      </div>
    </Card>
  );
}

function EditProject({
  workspaceId,
  project,
  onChanged,
}: {
  workspaceId: string;
  project: ProjectDetail;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [purpose, setPurpose] = useState(project.purpose ?? "");
  const [state, setState] = useState(project.state);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const submit = (event: SyntheticEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setProblem(null);

    client
      .updateProject(workspaceId, project.id, { purpose, state })
      .then(() => {
        setSaved(true);
        // Re-read rather than patch the copy on screen: the server stamps who
        // declared the state and when, and only it knows those.
        onChanged();
      })
      .catch((error: unknown) => {
        setProblem(describeError(error, "save this project"));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  return (
    <form className={styles.form} onSubmit={submit}>
      <h3 className={styles.formTitle}>Purpose and state</h3>

      <Field
        label="Purpose"
        name="purpose"
        value={purpose}
        onChange={(event) => {
          setPurpose(event.target.value);
        }}
        placeholder="What this project is for"
      />

      <div className={styles.control}>
        <label className={styles.label} htmlFor="project-state">
          State
        </label>
        <select
          className={styles.select}
          id="project-state"
          value={state}
          onChange={(event) => {
            setState(event.target.value);
          }}
        >
          {stateChoices(project.state).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </div>

      <p className={styles.hint}>A state is recorded as your declaration, never inferred.</p>

      {problem !== null && <InlineProblem error={problem} />}
      {saved && problem === null && <StatusNote>Saved. This project has been updated.</StatusNote>}

      <div className={styles.actions}>
        <Button type="submit" variant="primary" loading={saving}>
          Save changes
        </Button>
      </div>
    </form>
  );
}

function AddMember({
  workspaceId,
  projectId,
  current,
  onChanged,
}: {
  workspaceId: string;
  projectId: string;
  current: MemberEntry[];
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [personId, setPersonId] = useState("");
  const [role, setRole] = useState("");
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const loadPeople = useCallback(
    (signal: AbortSignal) => client.listMembers(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(loadPeople, "load the people in this workspace");

  const taken = new Set(current.map((member) => member.personId));
  const candidates =
    state.status === "ready"
      ? state.data.filter(
          (member) => member.personId != null && !taken.has(member.personId),
          // A member with no person record has nothing to add to a project, so
          // they are skipped rather than offered as an option that would fail.
        )
      : [];

  const submit = (event: SyntheticEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (personId === "") return;

    const chosen = candidates.find((member) => member.personId === personId);
    const name = chosen?.displayName ?? chosen?.email ?? "That person";

    setAdding(true);
    setAdded(null);
    setProblem(null);

    const trimmed = role.trim();
    client
      .addProjectMember(
        workspaceId,
        projectId,
        trimmed === "" ? { personId } : { personId, projectRole: trimmed },
      )
      .then(() => {
        setAdded(name);
        setPersonId("");
        setRole("");
        onChanged();
      })
      .catch((error: unknown) => {
        setProblem(describeError(error, "add this person to the project"));
      })
      .finally(() => {
        setAdding(false);
      });
  };

  return (
    <form className={styles.form} onSubmit={submit}>
      <h3 className={styles.formTitle}>Add someone</h3>

      {state.status === "loading" && (
        <LoadingState label="the people in this workspace" lines={2} />
      )}

      {state.status === "failed" && <InlineProblem error={state.error} onRetry={reload} />}

      {state.status === "ready" && candidates.length === 0 && (
        <p className={styles.hint}>Everyone in this workspace is already on this project.</p>
      )}

      {state.status === "ready" && candidates.length > 0 && (
        <>
          <div className={styles.control}>
            <label className={styles.label} htmlFor="project-person">
              Person
            </label>
            <select
              className={styles.select}
              id="project-person"
              value={personId}
              onChange={(event) => {
                setPersonId(event.target.value);
              }}
            >
              <option value="">Choose a person</option>
              {candidates.map((member) => (
                <option key={member.personId} value={member.personId ?? ""}>
                  {member.displayName ?? member.email}
                </option>
              ))}
            </select>
          </div>

          <Field
            label="Role on this project"
            name="projectRole"
            list="project-role-options"
            value={role}
            onChange={(event) => {
              setRole(event.target.value);
            }}
            placeholder="Frontend"
            hint="Their own words for their part here. Optional."
          />
          <datalist id="project-role-options">
            {ROLE_SUGGESTIONS.map((suggestion) => (
              <option key={suggestion} value={suggestion} />
            ))}
          </datalist>

          {problem !== null && <InlineProblem error={problem} />}
          {added !== null && problem === null && (
            <StatusNote>{`${added} was added to this project.`}</StatusNote>
          )}

          <div className={styles.actions}>
            <Button type="submit" variant="primary" loading={adding} disabled={personId === ""}>
              Add to project
            </Button>
          </div>
        </>
      )}
    </form>
  );
}

function CurrentMembers({
  workspaceId,
  projectId,
  current,
  onChanged,
}: {
  workspaceId: string;
  projectId: string;
  current: MemberEntry[];
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  /**
   * Two clicks, inline, rather than a modal.
   *
   * A dialog for this would move focus out of the list, cover the row being
   * talked about, and have to be dismissed before the reader could check they
   * had the right person — for an action that is reversible and preserves
   * history anyway. The second click happens where the first one did, so the
   * name stays on screen throughout.
   */
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const remove = (personId: string): void => {
    setBusy(personId);
    setProblem(null);

    client
      .removeProjectMember(workspaceId, projectId, personId)
      .then(() => {
        setConfirming(null);
        onChanged();
      })
      .catch((error: unknown) => {
        setProblem(describeError(error, "remove this person from the project"));
      })
      .finally(() => {
        setBusy(null);
      });
  };

  return (
    <div className={styles.form}>
      <h3 className={styles.formTitle}>People on this project</h3>
      <p className={styles.hint}>Removing keeps the history: the entry stays, closed.</p>

      {problem !== null && <InlineProblem error={problem} />}

      {current.length === 0 ? (
        <p className={styles.hint}>Nobody added yet.</p>
      ) : (
        <ul className={styles.rows}>
          {current.map((member) => (
            <li className={styles.row} key={member.personId}>
              <span className={styles.rowName}>{member.displayName}</span>
              <span className={styles.rowRole}>{member.projectRole ?? "No role set"}</span>
              {confirming === member.personId ? (
                <span className={styles.rowActions}>
                  <Button
                    size="sm"
                    variant="primary"
                    loading={busy === member.personId}
                    aria-label={`Confirm removal of ${member.displayName} from this project`}
                    onClick={() => {
                      remove(member.personId);
                    }}
                  >
                    Confirm removal
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === member.personId}
                    aria-label={`Keep ${member.displayName} on this project`}
                    onClick={() => {
                      setConfirming(null);
                    }}
                  >
                    Cancel
                  </Button>
                </span>
              ) : (
                <Button
                  size="sm"
                  aria-label={`Remove ${member.displayName} from this project`}
                  onClick={() => {
                    setProblem(null);
                    setConfirming(member.personId);
                  }}
                >
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The four rollup groups as one newest-first wall.
 *
 * Interleaved rather than sectioned because a reader arriving at a project asks
 * "what happened here", not "what happened here of kind three" — and four short
 * lists, three of them usually empty, read as a page of empty states.
 */
function workItems(project: ProjectDetail, credits: ReadonlyMap<string, string>): WorkItem[] {
  const rollup = project.rollup;
  const groups: readonly { kind: string; facts: ProjectFact[] }[] = [
    { kind: "Delivered", facts: rollup.delivered ?? [] },
    { kind: "Decision", facts: rollup.decisions ?? [] },
    { kind: "Blocker", facts: rollup.blockers ?? [] },
    { kind: "Open question", facts: rollup.openQuestions ?? [] },
  ];

  const items: WorkItem[] = [];
  for (const group of groups) {
    for (const fact of group.facts) {
      items.push({
        key: `${group.kind}:${fact.statement}`,
        kind: group.kind,
        statement: fact.statement,
        credit: credits.get(fact.statement) ?? null,
        occurredAt: fact.occurredAt ?? null,
        sources: fact.sources ?? [],
      });
    }
  }

  return items.sort(newestFirst);
}

/** Newest first, with undated facts last: a missing timestamp is missing data,
 * and sorting it to the front would present it as the latest news. */
function newestFirst(a: WorkItem, b: WorkItem): number {
  if (a.occurredAt === null && b.occurredAt === null) return 0;
  if (a.occurredAt === null) return 1;
  if (b.occurredAt === null) return -1;
  // ISO 8601 in UTC sorts correctly as text, so no Date is constructed here.
  return b.occurredAt.localeCompare(a.occurredAt);
}

/**
 * Who the evidence credits, keyed by statement. See `CREDIT_LOOKUP`.
 *
 * Swallows its own failure on purpose: a credit is an addition to a tile that
 * is already complete and checkable without it, so a page that fails because
 * the enrichment failed would be strictly worse than one that renders.
 */
async function creditsFor(
  client: CairnClient,
  workspaceId: string,
  projectName: string,
  signal: AbortSignal,
): Promise<ReadonlyMap<string, string>> {
  const credits = new Map<string, string>();

  try {
    const page = await client.listFacts(
      workspaceId,
      { project: [projectName], limit: CREDIT_LOOKUP },
      { signal },
    );
    for (const fact of page.items ?? []) {
      const mention = fact.people?.[0]?.mention;
      if (mention === undefined) continue;
      if (!credits.has(fact.statement)) credits.set(fact.statement, mention);
    }
  } catch {
    return credits;
  }

  return credits;
}

/**
 * One row per person, preferring a current membership.
 *
 * Somebody can be added, removed and added again, so the payload can hold
 * several rows for one person. Showing them all would put the same face in the
 * grid twice, and letting the older row win would mark somebody who is on the
 * project now as removed.
 */
function oneRowPerPerson(members: MemberEntry[]): MemberEntry[] {
  const byPerson = new Map<string, MemberEntry>();

  for (const member of members) {
    const held = byPerson.get(member.personId);
    if (held === undefined || (held.removedAt != null && member.removedAt == null)) {
      byPerson.set(member.personId, member);
    }
  }

  return [...byPerson.values()];
}

/** The three states offered, plus the project's own if it is something else —
 * so an existing `unknown` or `blocked` project can have its purpose edited
 * without the form silently declaring a state nobody chose. */
function stateChoices(current: string): { value: string; label: string }[] {
  const known = STATE_CHOICES.some((choice) => choice.value === current);
  return known ? [...STATE_CHOICES] : [...STATE_CHOICES, { value: current, label: current }];
}

function declaredBy(project: ProjectDetail): string {
  if (project.stateDeclaredAt == null) return "Nobody has declared a state for this project";
  const who = project.stateDeclaredBy ?? "somebody in this workspace";
  return `State declared by ${who} on ${asDate(project.stateDeclaredAt)}`;
}

function asDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
