import { ApiError, type TaskDetail } from "@cairn/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { TaskDetailPage } from "./TaskDetailPage.js";

/**
 * One task's page: hero, workflow moves, edits, and the audit trail.
 *
 * The workflow table is copied client-side for the buttons, so the
 * table-driven test below is the one that keeps the copy honest. The 409
 * tests are about voice: a workflow refusal is the product speaking, and the
 * server's own sentence must reach the reader verbatim.
 */

const WORKSPACE = SESSION.workspaces[0]!.workspace.id;
const TASK_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const PROJECT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const PERSON_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc";

const PROJECT = {
  id: PROJECT_ID,
  name: "Atlas",
  purpose: "The payments ledger.",
  state: "active",
  sources: [],
  members: [
    {
      personId: PERSON_ID,
      displayName: "Priya Nair",
      projectRole: "Backend",
      addedBy: "Ali Rahman",
      addedAt: "2026-08-01T09:00:00Z",
      removedBy: null as string | null,
      removedAt: null as string | null,
    },
    {
      personId: "dddddddd-dddd-dddd-dddd-dddddddddddd",
      displayName: "Jo Park",
      projectRole: null,
      addedBy: "Ali Rahman",
      addedAt: "2026-08-01T09:00:00Z",
      removedBy: null as string | null,
      removedAt: null as string | null,
    },
  ],
  rollup: { delivered: [], blockers: [], openQuestions: [], decisions: [] },
};

const EVENTS = [
  { at: "2026-08-10T09:00:00Z", sentence: "Ali Rahman created this task." },
  { at: "2026-08-11T10:00:00Z", sentence: "Priya Nair moved this task from To do to In progress." },
  {
    at: "2026-08-12T11:00:00Z",
    sentence: "Priya Nair moved this task from In progress to In review.",
  },
];

function task(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    id: TASK_ID,
    projectId: PROJECT_ID,
    title: "Ship the importer",
    description: "First pass at the CSV importer.",
    state: "todo",
    priority: "normal",
    assigneePersonId: PERSON_ID,
    assigneeName: "Priya Nair",
    dueOn: "2026-09-01",
    createdBy: "Ali Rahman",
    createdAt: "2026-08-10T09:00:00Z",
    archivedAt: null,
    events: EVENTS,
    ...overrides,
  };
}

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    getTask: vi.fn(() => Promise.resolve(task())),
    getProject: vi.fn(() => Promise.resolve(PROJECT)),
    ...overrides,
  });
}

function renderTask(stub = client()): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <TaskDetailPage taskId={TASK_ID} />
    </AppLayout>,
    { client: stub, route: `/tasks/${TASK_ID}` },
  );
}

/** The 409 the API sends when the reviewer and the approver are one person. */
const HANDOFF_SENTENCE =
  "The user who sent this task to review cannot be the one who " +
  "approves it as done; review means somebody else looked.";

function handoffError(): ApiError {
  return new ApiError({
    type: "https://cairn.example/problems/task-review-handoff",
    title: "Review needs a second pair of eyes",
    status: 409,
    detail: HANDOFF_SENTENCE,
  });
}

describe("the task hero", () => {
  it("shows title, state, priority, project link, assignee link and due date", async () => {
    renderTask();

    const heading = await screen.findByRole("heading", { name: /ship the importer/i });
    expect(heading).toBeVisible();

    expect(screen.getByLabelText(/task state: to do/i)).toBeVisible();
    // The pill, not the edit form's "Normal" option: first match in the hero.
    expect(screen.getAllByText("Normal")[0]).toBeVisible();

    const projectLink = screen.getByRole("link", { name: "Atlas" });
    expect(projectLink).toHaveAttribute("href", `/projects/${PROJECT_ID}`);

    const assigneeLink = screen.getByRole("link", { name: /priya nair/i });
    expect(assigneeLink).toHaveAttribute("href", `/people/${PERSON_ID}`);

    // The due date, as a readable day rather than a raw ISO string.
    expect(screen.getByText(/1 sept? 2026/i)).toBeVisible();
  });

  it("says Unassigned plainly when nobody is assigned", async () => {
    renderTask(
      client({
        getTask: vi.fn(() => Promise.resolve(task({ assigneePersonId: null, assigneeName: null }))),
      }),
    );

    await screen.findByRole("heading", { name: /ship the importer/i });
    // Once in the hero, once as the edit form's option — both honest.
    expect(screen.getAllByText("Unassigned")[0]).toBeVisible();
    expect(screen.queryByRole("link", { name: /priya nair/i })).toBeNull();
  });

  it("says Archived when the task is archived", async () => {
    renderTask(
      client({
        getTask: vi.fn(() => Promise.resolve(task({ archivedAt: "2026-08-15T09:00:00Z" }))),
      }),
    );

    await screen.findByRole("heading", { name: /ship the importer/i });
    expect(screen.getByText("Archived")).toBeVisible();
  });
});

describe("the description", () => {
  it("renders the text as paragraphs", async () => {
    renderTask();
    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /description/i });
    expect(within(region).getByText("First pass at the CSV importer.")).toBeVisible();
  });

  it("says No description when there is none", async () => {
    renderTask(client({ getTask: vi.fn(() => Promise.resolve(task({ description: "" }))) }));
    await screen.findByRole("heading", { name: /ship the importer/i });
    expect(screen.getByText("No description.")).toBeVisible();
  });
});

describe("moving a task", () => {
  // The client-side copy of the server's closed table, held to it here.
  it.each([
    ["todo", ["Start", "Mark blocked"]],
    ["in_progress", ["Send to review", "Mark blocked"]],
    ["in_review", ["Mark done", "Send back"]],
    ["blocked", ["Unblock", "Return to to-do"]],
    ["done", []],
  ] as const)("from %s offers exactly %j", async (state, labels) => {
    renderTask(client({ getTask: vi.fn(() => Promise.resolve(task({ state }))) }));

    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /move this task/i });

    const offered = within(region)
      .queryAllByRole("button")
      .map((button) => button.textContent.trim());
    expect(offered).toEqual([...labels]);
  });

  it("moves the task and re-reads it", async () => {
    const setTaskState = vi.fn(() => Promise.resolve(task({ state: "in_progress" })));
    const getTask = vi
      .fn()
      .mockResolvedValueOnce(task())
      .mockResolvedValue(task({ state: "in_progress" }));
    renderTask(client({ getTask, setTaskState }));

    await screen.findByRole("heading", { name: /ship the importer/i });
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() => {
      expect(setTaskState).toHaveBeenCalledWith(WORKSPACE, TASK_ID, "in_progress");
    });
    // The page re-read the task rather than patching the copy on screen.
    expect(await screen.findByLabelText(/task state: in progress/i)).toBeVisible();
    expect(getTask.mock.calls.length).toBeGreaterThan(1);
  });

  it("surfaces the review-handoff refusal in the server's own words", async () => {
    renderTask(
      client({
        getTask: vi.fn(() => Promise.resolve(task({ state: "in_review" }))),
        setTaskState: vi.fn(() => Promise.reject(handoffError())),
      }),
    );

    await screen.findByRole("heading", { name: /ship the importer/i });
    await userEvent.click(screen.getByRole("button", { name: "Mark done" }));

    // Verbatim: the sentence is the product speaking, not copy to paraphrase.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(HANDOFF_SENTENCE);
  });

  it("says done is final, with no buttons", async () => {
    renderTask(client({ getTask: vi.fn(() => Promise.resolve(task({ state: "done" }))) }));

    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /move this task/i });
    expect(
      within(region).getByText(
        "Done is final. A task closed in error is archived, and the work reopened as a new task.",
      ),
    ).toBeVisible();
    expect(within(region).queryByRole("button")).toBeNull();
  });

  it("offers no moves on an archived task", async () => {
    renderTask(
      client({
        getTask: vi.fn(() =>
          Promise.resolve(task({ state: "in_progress", archivedAt: "2026-08-15T09:00:00Z" })),
        ),
      }),
    );

    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /move this task/i });
    expect(within(region).queryByRole("button")).toBeNull();
    expect(within(region).getByText(/an archived task cannot move/i)).toBeVisible();
  });
});

describe("editing a task", () => {
  async function openEdit(): Promise<HTMLElement> {
    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /^edit$/i });
    await userEvent.click(within(region).getByText("Edit this task"));
    return region;
  }

  it("PATCHes only the fields that changed", async () => {
    const updateTask = vi.fn(() => Promise.resolve(task({ title: "Ship the importer, v2" })));
    renderTask(client({ updateTask }));

    const region = await openEdit();
    const title = within(region).getByLabelText("Title");
    await userEvent.clear(title);
    await userEvent.type(title, "Ship the importer, v2");
    await userEvent.click(within(region).getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(WORKSPACE, TASK_ID, {
        title: "Ship the importer, v2",
      });
    });
  });

  it("sends an explicit null to unassign", async () => {
    const updateTask = vi.fn(() => Promise.resolve(task({ assigneePersonId: null })));
    renderTask(client({ updateTask }));

    const region = await openEdit();
    await userEvent.selectOptions(within(region).getByLabelText("Assignee"), "");
    await userEvent.click(within(region).getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(WORKSPACE, TASK_ID, { assigneePersonId: null });
    });
  });

  it("disables editing on an archived task, with one sentence", async () => {
    renderTask(
      client({
        getTask: vi.fn(() => Promise.resolve(task({ archivedAt: "2026-08-15T09:00:00Z" }))),
      }),
    );

    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /^edit$/i });
    expect(
      within(region).getByText("An archived task is read-only. Restore it to make changes."),
    ).toBeVisible();
    expect(within(region).queryByLabelText("Title")).toBeNull();
  });
});

describe("archive and restore", () => {
  it("archives, then the refreshed task offers restore", async () => {
    const archiveTask = vi.fn(() => Promise.resolve(task({ archivedAt: "2026-08-21T09:00:00Z" })));
    const getTask = vi
      .fn()
      .mockResolvedValueOnce(task())
      .mockResolvedValue(task({ archivedAt: "2026-08-21T09:00:00Z" }));
    renderTask(client({ getTask, archiveTask }));

    await screen.findByRole("heading", { name: /ship the importer/i });
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));

    await waitFor(() => {
      expect(archiveTask).toHaveBeenCalledWith(WORKSPACE, TASK_ID);
    });
    expect(await screen.findByRole("button", { name: "Restore" })).toBeVisible();
  });

  it("surfaces a refusal through the shared error copy", async () => {
    renderTask(client({ archiveTask: vi.fn(() => Promise.reject(apiError(403))) }));

    await screen.findByRole("heading", { name: /ship the importer/i });
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/does not have access/i);
  });
});

describe("the history", () => {
  it("lists every event in order, in the server's sentences", async () => {
    renderTask();

    await screen.findByRole("heading", { name: /ship the importer/i });
    const region = screen.getByRole("region", { name: /history/i });
    const entries = within(region).getAllByRole("listitem");

    expect(entries).toHaveLength(EVENTS.length);
    EVENTS.forEach((event, index) => {
      expect(entries[index]).toHaveTextContent(event.sentence);
    });
  });
});

describe("loading, failure and absence", () => {
  it("treats a 404 as task not found", async () => {
    renderTask(client({ getTask: vi.fn(() => Promise.reject(apiError(404))) }));

    expect(await screen.findByText("Task not found")).toBeVisible();
    expect(screen.getByText("No task in this workspace matches this link.")).toBeVisible();
  });

  it("offers a retry when the read fails, and it works", async () => {
    const getTask = vi.fn().mockRejectedValueOnce(apiError(503)).mockResolvedValue(task());
    renderTask(client({ getTask }));

    expect(await screen.findByText("This task could not be loaded")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByRole("heading", { name: /ship the importer/i })).toBeVisible();
  });
});

describe("what the page refuses to say", () => {
  it("carries no score, rank or count of anybody's anything", async () => {
    renderTask();
    await screen.findByRole("heading", { name: /ship the importer/i });

    const main = await screen.findByRole("main");
    const text = main.textContent;

    expect(text).not.toMatch(/\b(?:score\w*|rank\w*|most|top|productivity|velocity)\b/i);
    expect(text).not.toMatch(/\d+ (tasks?|completed)/i);
  });
});
