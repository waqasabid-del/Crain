"use client";

import type { TaskCreateBody } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { useEffect, useId, useRef, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { InlineProblem } from "./InlineProblem.js";
import styles from "./QuickAddTask.module.css";

/** Somebody a task can be handed to: a current member of its project. */
export interface QuickAddMember {
  personId: string;
  displayName: string;
}

/** One project this composer may create into, with the people work on it can
 * go to. */
export interface QuickAddProject {
  id: string;
  name: string;
  members: readonly QuickAddMember[];
}

/**
 * Where a column's quick composer creates.
 *
 * A discriminated union rather than a project id beside an "ask for it" flag:
 * the two cases carry different data — a fixed target knows its members, a
 * chosen one cannot know them until the reader picks — and a boolean would let
 * a caller ask for a project select while supplying no projects to choose from.
 */
export type QuickAddTarget =
  /** One project, already decided: a project board, or a single project tab. */
  | { kind: "fixed"; projectId: string; members: readonly QuickAddMember[] }
  /** Several projects pooled: the composer asks which one. */
  | { kind: "choose"; projects: readonly QuickAddProject[] };

/** The four priorities the composer offers, led by the default. */
const PRIORITY_CHOICES: readonly { value: string; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
];

/**
 * "+ Add task" at the foot of a board column, and the composer it opens in
 * place.
 *
 * The Jira idiom, and the reason it is worth having beside the page's fuller
 * "New task" panel: work is added where the reader is looking. A column's
 * composer already knows the two things the header's panel has to ask for —
 * which column, and so which state — so it asks for a title and little else.
 *
 * It deliberately omits description and due date. Those belong to the fuller
 * panel: a quick composer that grew a textarea and a date field would be the
 * fuller panel, drawn twice, and the point of this one is that it costs a title
 * and Enter. Both can be added afterwards on the task's own page.
 *
 * Open/closed is owned by the board above, not here, so that only one composer
 * stands open across the whole board — two open composers are two half-typed
 * tasks, and the reader loses track of which column they are adding to.
 */
export function QuickAddTask({
  workspaceId,
  columnLabel,
  state,
  target,
  canAssign,
  open,
  onOpen,
  onClose,
  onCreated,
}: {
  workspaceId: string;
  /** The column's own name, for the accessible names of these controls. */
  columnLabel: string;
  /** The state this column creates into — `todo`, `in_progress`, `in_review`
   * or `done`. `blocked` is not creatable: a task is blocked by something that
   * happened to it. */
  state: string;
  target: QuickAddTarget;
  /** False in the unassigned column, which *is* the column for work nobody
   * holds: the composer hides the select and creates with no assignee. */
  canAssign: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  /** The create landed — the board re-reads. */
  onCreated: () => void;
}): ReactNode {
  const client = useApiClient();
  const titleId = useId();
  const projectId = useId();
  const priorityId = useId();
  const assigneeId = useId();
  const formRef = useRef<HTMLFormElement | null>(null);
  const addRef = useRef<HTMLButtonElement | null>(null);
  const titleRef = useRef<HTMLInputElement | null>(null);
  // Set only by Escape and Cancel: a close the reader asked for returns their
  // focus to the control they opened, while a close caused by anything else
  // must not yank focus out from under them.
  const restoreFocus = useRef(false);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("normal");
  const [assignee, setAssignee] = useState("");
  const [project, setProject] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  /*
   * Where focus sits.
   *
   * On open, and again the moment a request settles — the title field is
   * disabled while one is in flight, and a disabled control cannot take focus,
   * so focusing it from the request's own callback would silently do nothing.
   * Keyed on `saving` instead: when it falls back to false the field is
   * enabled again, and the reader is put back in it to type the next task or
   * correct the one that was refused.
   */
  useEffect(() => {
    if (open) {
      if (!saving) titleRef.current?.focus();
      return;
    }
    if (restoreFocus.current) {
      restoreFocus.current = false;
      addRef.current?.focus();
    }
  }, [open, saving]);

  const chosenProject =
    target.kind === "fixed"
      ? null
      : (target.projects.find((candidate) => candidate.id === project) ?? null);
  const members = target.kind === "fixed" ? target.members : (chosenProject?.members ?? []);
  const createInto = target.kind === "fixed" ? target.projectId : project;
  // A title of spaces is not a task. The button stays disabled rather than
  // accepting the click and answering with red: nothing has gone wrong yet.
  const ready = title.trim() !== "" && createInto !== "";

  function cancel(): void {
    restoreFocus.current = true;
    onClose();
  }

  /*
   * Escape closes without creating, wherever focus sits inside the composer.
   *
   * A native listener on the form rather than an `onKeyDown` prop: React's
   * handler on a `<form>` is a keyboard listener on a non-interactive element,
   * which is exactly the thing an accessibility linter is right to refuse. The
   * form is a container; its controls are what the reader operates, and this
   * listens on the container the way the platform does.
   */
  useEffect(() => {
    const form = formRef.current;
    if (!open || form === null) return undefined;

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      // Contained: a page-level Escape handler must not also act on this one.
      event.stopPropagation();
      restoreFocus.current = true;
      onClose();
    };

    form.addEventListener("keydown", onKeyDown);
    return () => {
      form.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  const submit = (event: SyntheticEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (!ready || saving) return;
    setProblem(null);
    setSaving(true);

    const body: TaskCreateBody = {
      title: title.trim(),
      // Both omitted by design — see this component's note. The API defaults
      // description to empty and a task with no due date simply has none.
      description: "",
      priority,
      state,
      // Spread rather than sending an empty string: an unassigned task has no
      // assignee, not an assignee called "".
      ...(canAssign && assignee !== "" ? { assigneePersonId: assignee } : {}),
    };

    client
      .createTask(workspaceId, createInto, body)
      .then(() => {
        // The composer stays open with the title cleared: an owner filling a
        // column adds several in a row, and closing after each one would make
        // them re-open it every time. Focus follows from the effect above,
        // once the field is enabled again.
        setTitle("");
        onCreated();
      })
      .catch((error: unknown) => {
        // The typed values are deliberately left alone: a refusal is something
        // to adjust, not a reason to retype the task.
        setProblem(describeError(error, "create this task"));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  if (!open) {
    return (
      <button
        type="button"
        ref={addRef}
        className={styles.add}
        onClick={onOpen}
        aria-label={`Add task to ${columnLabel}`}
      >
        {/* The plus is decoration; the words carry the action, and the
          accessible name starts with them so it matches what is on screen. */}
        <span aria-hidden="true">+</span> Add task
      </button>
    );
  }

  return (
    <form
      className={styles.composer}
      ref={formRef}
      aria-label={`Add task to ${columnLabel}`}
      onSubmit={submit}
    >
      <div className={styles.control}>
        <label className={styles.label} htmlFor={titleId}>
          Title
        </label>
        {/* Enter in the title submits, because a single-line input in a form
          does — no key handler pretending to be a form. */}
        <input
          className={styles.input}
          id={titleId}
          ref={titleRef}
          type="text"
          maxLength={200}
          placeholder="What needs doing?"
          value={title}
          disabled={saving}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </div>

      {target.kind === "choose" && (
        <div className={styles.control}>
          <label className={styles.label} htmlFor={projectId}>
            Project
          </label>
          <select
            className={styles.select}
            id={projectId}
            value={project}
            disabled={saving}
            onChange={(event) => {
              setProject(event.target.value);
              // The old choice may not be a member of the new project.
              setAssignee("");
            }}
          >
            <option value="">Choose a project</option>
            {target.projects.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {canAssign && (
        <div className={styles.control}>
          <label className={styles.label} htmlFor={assigneeId}>
            Assignee
          </label>
          <select
            className={styles.select}
            id={assigneeId}
            value={assignee}
            disabled={saving}
            onChange={(event) => {
              setAssignee(event.target.value);
            }}
          >
            {/* The honest default: a task nobody holds yet is a true
              statement, not a gap the form should fill in. */}
            <option value="">Nobody yet</option>
            {members.map((member) => (
              <option key={member.personId} value={member.personId}>
                {member.displayName}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className={styles.control}>
        <label className={styles.label} htmlFor={priorityId}>
          Priority
        </label>
        <select
          className={styles.select}
          id={priorityId}
          value={priority}
          disabled={saving}
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

      <div className={styles.actions}>
        <Button type="submit" size="sm" variant="primary" loading={saving} disabled={!ready}>
          Add
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={saving} onClick={cancel}>
          Cancel
        </Button>
      </div>

      {problem !== null && <InlineProblem error={problem} />}
    </form>
  );
}
