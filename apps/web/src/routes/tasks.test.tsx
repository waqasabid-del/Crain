import {
  ApiError,
  type ProjectDetail,
  type ProjectList,
  type TaskDetail,
  type TaskList,
  type TaskSummary,
} from "@cairn/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { TasksPage } from "./TasksPage.js";

/**
 * The owner's board: the workspace's tasks in columns ordered by what the
 * owner does about them.
 *
 * The assertions here are as much about what the screen must *not* be as what
 * it is. A view of everybody's work is the easiest place in the product to
 * grow a scoreboard — a count in a column header, an "N unassigned", a
 * velocity figure — so one test holds the rendered text to the same
 * vocabulary rule the dashboard and People page are held to.
 */

const WORKSPACE = "22222222-2222-2222-2222-222222222222";
const ATLAS = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const BOREALIS = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const PRIYA = "77777777-7777-7777-7777-777777777777";
const MARA = "88888888-8888-8888-8888-888888888888";

function task(overrides: Partial<TaskSummary> & { id: string; title: string }): TaskSummary {
  return {
    state: "todo",
    priority: "normal",
    projectId: ATLAS,
    createdAt: "2026-08-10T09:00:00Z",
    description: "",
    ...overrides,
  };
}

const ATLAS_TASKS: TaskSummary[] = [
  task({
    id: "11111111-aaaa-1111-1111-111111111111",
    title: "Wire the export",
    state: "in_progress",
    priority: "high",
    assigneePersonId: PRIYA,
    assigneeName: "Priya Shah",
    dueOn: "2026-08-28",
  }),
  task({ id: "22222222-aaaa-2222-2222-222222222222", title: "Draft the notice" }),
  task({ id: "33333333-aaaa-3333-3333-333333333333", title: "Ship the audit", state: "done" }),
  task({
    id: "55555555-aaaa-5555-5555-555555555555",
    title: "Review the schema",
    state: "in_review",
    assigneePersonId: PRIYA,
    assigneeName: "Priya Shah",
  }),
  task({
    id: "66666666-aaaa-6666-6666-666666666666",
    title: "Plan the rollout",
    assigneePersonId: PRIYA,
    assigneeName: "Priya Shah",
  }),
];

const BOREALIS_TASKS: TaskSummary[] = [
  task({
    id: "44444444-bbbb-4444-4444-444444444444",
    title: "Map the sources",
    state: "blocked",
    projectId: BOREALIS,
    assigneePersonId: MARA,
    assigneeName: "Mara Voss",
  }),
  task({
    id: "99999999-bbbb-9999-9999-999999999999",
    title: "Chart the risks",
    projectId: BOREALIS,
  }),
];

const PROJECTS: ProjectList = {
  projects: [
    { id: ATLAS, name: "Atlas", state: "active" },
    { id: BOREALIS, name: "Borealis", state: "active" },
  ],
};

function detail(
  id: string,
  name: string,
  members: { personId: string; displayName: string }[],
): ProjectDetail {
  return {
    id,
    name,
    state: "active",
    rollup: {},
    members: members.map((member) => ({ ...member, addedAt: "2026-01-05T09:00:00Z" })),
  };
}

const ATLAS_DETAIL = detail(ATLAS, "Atlas", [{ personId: PRIYA, displayName: "Priya Shah" }]);
const BOREALIS_DETAIL = detail(BOREALIS, "Borealis", [
  { personId: MARA, displayName: "Mara Voss" },
]);

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listProjects: vi.fn(() => Promise.resolve(PROJECTS)),
    listTasks: vi.fn((_workspaceId: string, projectId: string) =>
      Promise.resolve<TaskList>({ tasks: projectId === ATLAS ? ATLAS_TASKS : BOREALIS_TASKS }),
    ),
    getProject: vi.fn((_workspaceId: string, projectId: string) =>
      Promise.resolve(projectId === ATLAS ? ATLAS_DETAIL : BOREALIS_DETAIL),
    ),
    ...overrides,
  });
}

/** A session whose one membership carries the given role. */
function sessionAs(role: "owner" | "admin" | "member" | "viewer"): typeof SESSION {
  const membership = SESSION.workspaces[0];
  if (membership === undefined) throw new Error("SESSION has no workspace");
  return { ...SESSION, workspaces: [{ ...membership, role }] };
}

function renderPage(stub = client()): void {
  renderRoute(
    <AppLayout>
      <TasksPage />
    </AppLayout>,
    { client: stub, route: "/tasks" },
  );
}

describe("tasks", () => {
  it("renders the five columns in working order", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    // Await content the data produced, never a region that exists while
    // loading — the loading skeleton has no headings.
    await within(main).findByText("Wire the export");

    const headings = within(main)
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["Assign", "To do", "In progress", "Test", "Completed"]);
  });

  it("leads with the cross-project unassigned tasks, once each, and omits done ones", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const assignColumn = within(main).getByRole("region", { name: "Assign" });
    expect(within(assignColumn).getByText("Draft the notice")).toBeVisible();
    // Cross-project: Borealis's unassigned task is here too, with its project.
    expect(within(assignColumn).getByText("Chart the risks")).toBeVisible();
    expect(within(assignColumn).getByText("Borealis")).toBeVisible();
    // A done task without an assignee is finished work, not a gap to fill.
    expect(within(assignColumn).queryByText("Ship the audit")).toBeNull();
    // An assigned to-do belongs to "To do" and only there — a card shown in
    // two columns reads as two tasks.
    expect(within(assignColumn).queryByText("Plan the rollout")).toBeNull();
    const todoColumn = within(main).getByRole("region", { name: "To do" });
    expect(within(todoColumn).getByText("Plan the rollout")).toBeVisible();
    expect(within(todoColumn).queryByText("Draft the notice")).toBeNull();
  });

  it("lists every project in the tab row, led by All projects", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const row = within(main).getByRole("group", { name: "Show one project" });
    const tabs = within(row)
      .getAllByRole("button")
      .map((button) => button.textContent);
    expect(tabs).toEqual(["All projects", "Atlas", "Borealis"]);
    // The project name alone — never a count beside it.
    expect(row.textContent).not.toMatch(/\d/);
  });

  it("starts on All projects, and marks the selected tab as current", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const row = within(main).getByRole("group", { name: "Show one project" });
    expect(within(row).getByRole("button", { name: "All projects" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(within(row).getByRole("button", { name: "Atlas" })).not.toHaveAttribute("aria-current");

    await userEvent.click(within(row).getByRole("button", { name: "Atlas" }));

    expect(within(row).getByRole("button", { name: "Atlas" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(within(row).getByRole("button", { name: "All projects" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("filters every column to the selected project, and says which it is showing", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");
    expect(within(main).getByRole("group", { name: "Tasks in every project" })).toBeVisible();

    await userEvent.click(within(main).getByRole("button", { name: "Atlas" }));

    // Atlas's work, in the columns it belongs to.
    const board = within(main).getByRole("group", { name: "Tasks in Atlas" });
    expect(within(board).getByText("Wire the export")).toBeVisible();
    expect(within(board).getByText("Draft the notice")).toBeVisible();
    expect(within(board).getByText("Review the schema")).toBeVisible();
    expect(within(board).getByText("Ship the audit")).toBeVisible();
    // Borealis's work is gone from every column, including Assign.
    expect(within(board).queryByText("Chart the risks")).toBeNull();
    expect(within(board).queryByText("Map the sources")).toBeNull();

    // And back again.
    await userEvent.click(within(main).getByRole("button", { name: "All projects" }));
    expect(
      within(within(main).getByRole("group", { name: "Tasks in every project" })).getByText(
        "Chart the risks",
      ),
    ).toBeVisible();
  });

  it("drops the project name from cards when one project is selected", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");
    // Pooled: the card says where the work lives, because nothing else does.
    expect(
      within(within(main).getByRole("region", { name: "Assign" })).getByRole("link", {
        name: "Borealis",
      }),
    ).toBeVisible();

    await userEvent.click(within(main).getByRole("button", { name: "Atlas" }));

    const board = within(main).getByRole("group", { name: "Tasks in Atlas" });
    expect(within(board).queryByRole("link", { name: "Atlas" })).toBeNull();
  });

  it("reaches and operates the tabs from the keyboard alone", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const atlas = within(main).getByRole("button", { name: "Atlas" });
    atlas.focus();
    expect(atlas).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(within(main).getByRole("group", { name: "Tasks in Atlas" })).toBeVisible();
  });

  it("keeps a failed project's tab, and says why rather than showing empty columns", async () => {
    const listTasks = vi.fn((_workspaceId: string, projectId: string) =>
      projectId === BOREALIS
        ? Promise.reject(apiError(500))
        : Promise.resolve<TaskList>({ tasks: ATLAS_TASKS }),
    );
    renderPage(client({ listTasks }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    // The tab stands: a project that could not be read must never look like a
    // project that no longer exists.
    await userEvent.click(within(main).getByRole("button", { name: "Borealis" }));

    expect(within(main).getByText(/tasks in borealis could not be read/i)).toBeVisible();
    expect(within(main).getByRole("button", { name: /try again/i })).toBeVisible();
    // No board at all — five empty columns would say "no work here", which is
    // not what happened.
    expect(within(main).queryByRole("region", { name: "Assign" })).toBeNull();
    expect(within(main).queryByText("Nothing here.")).toBeNull();
  });

  it("defaults the New task project to the selected one, still changeable", async () => {
    const createTask = vi.fn(() => Promise.resolve(ATLAS_TASKS[0] as TaskDetail));
    renderPage(client({ createTask }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    await userEvent.click(within(main).getByRole("button", { name: "Borealis" }));
    await userEvent.click(within(main).getByRole("button", { name: "New task" }));

    const projectSelect = within(main).getByRole("combobox", { name: "Project" });
    expect(projectSelect).toHaveValue(BOREALIS);
    // Its members are the ones offered, not the previous project's.
    const assigneeSelect = within(main).getByRole("combobox", { name: "Assignee" });
    expect(within(assigneeSelect).getByRole("option", { name: "Mara Voss" })).toBeVisible();
    expect(within(assigneeSelect).queryByRole("option", { name: "Priya Shah" })).toBeNull();

    // Still changeable.
    await userEvent.selectOptions(projectSelect, ATLAS);
    await userEvent.type(within(main).getByRole("textbox", { name: /title/i }), "Write the brief");
    await userEvent.click(within(main).getByRole("button", { name: "Create task" }));

    expect(createTask).toHaveBeenCalledWith(WORKSPACE, ATLAS, {
      title: "Write the brief",
      description: "",
      priority: "normal",
    });
  });

  it("renders the tab row even when the workspace has one project", async () => {
    renderPage(
      client({
        listProjects: vi.fn(() =>
          Promise.resolve({ projects: [{ id: ATLAS, name: "Atlas", state: "active" }] }),
        ),
      }),
    );

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const row = within(main).getByRole("group", { name: "Show one project" });
    expect(
      within(row)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["All projects", "Atlas"]);
  });

  it("shows a blocked task in the In progress column, with a Blocked pill", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const inProgress = within(main).getByRole("region", { name: "In progress" });
    expect(within(inProgress).getByText("Map the sources")).toBeVisible();
    expect(within(inProgress).getByText("Blocked")).toBeVisible();
    expect(within(inProgress).getByText("Mara Voss")).toBeVisible();
    // Blocked cards are read-only: unblocking belongs on the task's own page.
    expect(within(inProgress).queryByRole("button")).toBeNull();
    // The moving task carries no such pill.
    expect(within(main).getAllByText("Blocked")).toHaveLength(1);
  });

  it("assigns a task from the card, disabling the control while in flight", async () => {
    let settle!: (moved: TaskDetail) => void;
    const updateTask = vi.fn(
      () =>
        new Promise<TaskDetail>((resolve) => {
          settle = resolve;
        }),
    );
    const listProjects = vi.fn(() => Promise.resolve(PROJECTS));
    renderPage(client({ updateTask, listProjects }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Draft the notice");

    const assignColumn = within(main).getByRole("region", { name: "Assign" });
    const select = within(assignColumn).getByRole("combobox", {
      name: "Assign Draft the notice",
    });
    await userEvent.selectOptions(select, PRIYA);

    expect(updateTask).toHaveBeenCalledWith(WORKSPACE, "22222222-aaaa-2222-2222-222222222222", {
      assigneePersonId: PRIYA,
    });
    // In flight: the control is disabled rather than accepting a second name.
    expect(select).toBeDisabled();

    settle(ATLAS_TASKS[0] as TaskDetail);
    // Success re-reads the whole view rather than patching the card.
    await waitFor(() => {
      expect(listProjects).toHaveBeenCalledTimes(2);
    });
  });

  it("says a refused assignment beside the control, and keeps the card", async () => {
    renderPage(client({ updateTask: vi.fn(() => Promise.reject(apiError(403))) }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Draft the notice");

    const assignColumn = within(main).getByRole("region", { name: "Assign" });
    await userEvent.selectOptions(
      within(assignColumn).getByRole("combobox", { name: "Assign Draft the notice" }),
      PRIYA,
    );

    const alert = await within(assignColumn).findByRole("alert");
    expect(alert).toHaveTextContent(/does not have access/i);
    expect(within(assignColumn).getByText("Draft the notice")).toBeVisible();
  });

  it("marks a reviewed task done and re-reads the view", async () => {
    const setTaskState = vi.fn(() => Promise.resolve(ATLAS_TASKS[3] as TaskDetail));
    const listProjects = vi.fn(() => Promise.resolve(PROJECTS));
    renderPage(client({ setTaskState, listProjects }));

    const main = await screen.findByRole("main");
    const testColumn = await within(main).findByRole("region", { name: "Test" });
    await within(testColumn).findByText("Review the schema");

    await userEvent.click(
      within(testColumn).getByRole("button", { name: "Mark Review the schema done" }),
    );

    expect(setTaskState).toHaveBeenCalledWith(
      WORKSPACE,
      "55555555-aaaa-5555-5555-555555555555",
      "done",
    );
    await waitFor(() => {
      expect(listProjects).toHaveBeenCalledTimes(2);
    });
  });

  it("sends a reviewed task back to in progress", async () => {
    const setTaskState = vi.fn(() => Promise.resolve(ATLAS_TASKS[3] as TaskDetail));
    const listProjects = vi.fn(() => Promise.resolve(PROJECTS));
    renderPage(client({ setTaskState, listProjects }));

    const main = await screen.findByRole("main");
    const testColumn = await within(main).findByRole("region", { name: "Test" });
    await within(testColumn).findByText("Review the schema");

    await userEvent.click(
      within(testColumn).getByRole("button", { name: "Send Review the schema back" }),
    );

    expect(setTaskState).toHaveBeenCalledWith(
      WORKSPACE,
      "55555555-aaaa-5555-5555-555555555555",
      "in_progress",
    );
    await waitFor(() => {
      expect(listProjects).toHaveBeenCalledTimes(2);
    });
  });

  it("surfaces the API's review-handoff sentence verbatim on a 409", async () => {
    const sentence =
      "You sent this task to review, so somebody else must approve it. Ask a colleague to take a look.";
    const setTaskState = vi.fn(() =>
      Promise.reject(
        new ApiError({
          type: "https://cairn.example/problems/review-handoff",
          title: "Conflict",
          status: 409,
          detail: sentence,
        }),
      ),
    );
    renderPage(client({ setTaskState }));

    const main = await screen.findByRole("main");
    const testColumn = await within(main).findByRole("region", { name: "Test" });
    await within(testColumn).findByText("Review the schema");

    await userEvent.click(
      within(testColumn).getByRole("button", { name: "Mark Review the schema done" }),
    );

    const alert = await within(testColumn).findByRole("alert");
    // Verbatim: the server's sentence names the rule precisely, and a
    // paraphrase inviting a retry would be false.
    expect(alert).toHaveTextContent(sentence);
  });

  it("says the calm lines when Assign and Test stand empty", async () => {
    const quiet: TaskSummary[] = [
      task({
        id: "11111111-aaaa-1111-1111-111111111111",
        title: "Wire the export",
        state: "in_progress",
        assigneePersonId: PRIYA,
        assigneeName: "Priya Shah",
      }),
    ];
    renderPage(
      client({
        listTasks: vi.fn((_workspaceId: string, projectId: string) =>
          Promise.resolve<TaskList>({ tasks: projectId === ATLAS ? quiet : [] }),
        ),
      }),
    );

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    // The emptiness of these two is the good news an owner checks for, so
    // each says it in its own words rather than a generic line.
    const assignColumn = within(main).getByRole("region", { name: "Assign" });
    expect(within(assignColumn).getByText("Everything is assigned.")).toBeVisible();
    const testColumn = within(main).getByRole("region", { name: "Test" });
    expect(within(testColumn).getByText("Nothing is waiting for review.")).toBeVisible();
    // The other columns still stand — a board with missing columns reads as a
    // broken board — with their own quiet line.
    const todoColumn = within(main).getByRole("region", { name: "To do" });
    expect(within(todoColumn).getByText("Nothing here.")).toBeVisible();
  });

  it("shows done tasks only under Completed", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const completed = within(main).getByRole("region", { name: "Completed" });
    expect(within(completed).getByText("Ship the audit")).toBeVisible();
    expect(within(main).getAllByText("Ship the audit")).toHaveLength(1);
  });

  it("shows each assignee's name on their cards", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    const inProgress = within(main).getByRole("region", { name: "In progress" });
    // Once as the holder of "Wire the export" — never as a tally of any kind.
    expect(within(inProgress).getByText("Priya Shah")).toBeVisible();
    expect(within(inProgress).getByText("High")).toBeVisible();
    expect(within(inProgress).getByText(/due/i)).toBeVisible();
  });

  it("keeps the board when one project cannot be read, and names it", async () => {
    const listTasks = vi.fn((_workspaceId: string, projectId: string) =>
      projectId === BOREALIS
        ? Promise.reject(apiError(500))
        : Promise.resolve<TaskList>({ tasks: ATLAS_TASKS }),
    );
    renderPage(client({ listTasks }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    // A one-line note naming the project, not a page-level failure.
    expect(within(main).getByText(/tasks in borealis could not be read/i)).toBeVisible();
    expect(within(main).queryByText("Map the sources")).toBeNull();
    expect(within(main).getByRole("button", { name: /try again/i })).toBeVisible();
  });

  it("links each task to its own page", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    const link = await within(main).findByRole("link", { name: "Wire the export" });
    expect(link).toHaveAttribute("href", "/tasks/11111111-aaaa-1111-1111-111111111111");
  });

  it("links each card's project name to the project", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    const assignColumn = await within(main).findByRole("region", { name: "Assign" });
    const link = within(assignColumn).getByRole("link", { name: "Borealis" });
    expect(link).toHaveAttribute("href", `/projects/${BOREALIS}`);
  });

  it("offers a viewer no controls anywhere", async () => {
    renderPage(client({ getSession: vi.fn(() => Promise.resolve(sessionAs("viewer"))) }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Draft the notice");

    expect(within(main).queryByRole("button", { name: "New task" })).toBeNull();
    expect(within(main).queryByRole("combobox")).toBeNull();
    expect(within(main).queryByRole("button", { name: /mark .* done/i })).toBeNull();
    expect(within(main).queryByRole("button", { name: /send .* back/i })).toBeNull();
    // The fact is still said, quietly, rather than hidden with the control.
    expect(within(main).getAllByText("Unassigned").length).toBeGreaterThan(0);
  });

  it("offers a member the controls", async () => {
    renderPage(client({ getSession: vi.fn(() => Promise.resolve(sessionAs("member"))) }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Draft the notice");

    expect(within(main).getByRole("button", { name: "New task" })).toBeVisible();
    expect(within(main).getByRole("combobox", { name: "Assign Draft the notice" })).toBeVisible();
    expect(within(main).getByRole("button", { name: "Mark Review the schema done" })).toBeVisible();
  });

  it("creates a task on the chosen project and re-reads the view", async () => {
    const createTask = vi.fn(() => Promise.resolve(ATLAS_TASKS[0] as TaskDetail));
    const listProjects = vi.fn(() => Promise.resolve(PROJECTS));
    renderPage(client({ createTask, listProjects }));

    const main = await screen.findByRole("main");
    await within(main).findByText("Draft the notice");

    await userEvent.click(within(main).getByRole("button", { name: "New task" }));
    await userEvent.selectOptions(within(main).getByRole("combobox", { name: "Project" }), ATLAS);
    await userEvent.type(within(main).getByRole("textbox", { name: /title/i }), "Write the brief");
    await userEvent.selectOptions(within(main).getByRole("combobox", { name: "Assignee" }), PRIYA);
    await userEvent.click(within(main).getByRole("button", { name: "Create task" }));

    expect(createTask).toHaveBeenCalledWith(WORKSPACE, ATLAS, {
      title: "Write the brief",
      description: "",
      priority: "normal",
      assigneePersonId: PRIYA,
    });
    await waitFor(() => {
      expect(listProjects).toHaveBeenCalledTimes(2);
    });
    // The panel collapsed: the toggle offers to open it again.
    expect(within(main).getByRole("button", { name: "New task" })).toBeVisible();
  });

  it("asks the reader to join a workspace when they belong to none", async () => {
    renderPage(
      client({
        getSession: vi.fn(() => Promise.resolve({ ...SESSION, workspaces: [] })),
        listProjects: vi.fn(() => Promise.reject(new Error("must not be called"))),
      }),
    );

    const main = await screen.findByRole("main");
    expect(await within(main).findByText(/join a workspace to see its tasks/i)).toBeVisible();
    expect(within(main).queryByRole("alert")).toBeNull();
  });

  it("points at the projects screen when there are no projects at all", async () => {
    renderPage(client({ listProjects: vi.fn(() => Promise.resolve({ projects: [] })) }));

    const main = await screen.findByRole("main");
    expect(await within(main).findByText("No projects yet")).toBeVisible();
    const link = within(main).getByRole("link", { name: /go to projects/i });
    expect(link).toHaveAttribute("href", "/projects");
    expect(within(main).queryByRole("button", { name: "New task" })).toBeNull();
  });

  it("announces loading while the tasks are on their way", async () => {
    renderPage(
      client({
        listProjects: vi.fn(
          () =>
            new Promise<ProjectList>(() => {
              // Never resolves: the screen stays in its loading state.
            }),
        ),
      }),
    );

    const main = await screen.findByRole("main");
    const status = await within(main).findByRole("status");
    expect(status).toHaveTextContent(/loading the tasks in this workspace/i);
  });

  it("offers a retry after a whole-read failure, and recovers", async () => {
    const listProjects = vi.fn().mockRejectedValueOnce(apiError(500)).mockResolvedValue(PROJECTS);
    renderPage(client({ listProjects }));

    const main = await screen.findByRole("main");
    const alert = await within(main).findByRole("alert");
    expect(alert).toHaveTextContent(/could not be loaded/i);

    await userEvent.click(within(main).getByRole("button", { name: /try again/i }));
    expect(await within(main).findByText("Wire the export")).toBeVisible();
  });

  it("never counts, scores or measures anyone", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");
    // `main` includes the tab row, so the guard below covers it too — but the
    // row is asserted separately, because a count is likeliest to appear
    // exactly there, beside a project's name.
    expect(within(main).getByRole("group", { name: "Show one project" }).textContent).not.toMatch(
      /\d/,
    );
    const text = main.textContent;

    // No tally phrasing anywhere: the column is "Assign", never "Assign (4)",
    // and nothing says how many tasks anybody holds.
    expect(text).not.toMatch(/\d+\s*(tasks?|completed|done|unassigned)/i);
    // The vocabulary, including in negation — same rule as the dashboard.
    expect(text).not.toMatch(
      /\b(?:top|most|least|rank\w*|score\w*|leaderboard|productivity|performance|velocity)\b/i,
    );
    expect(text).not.toMatch(/\d+\s?%/);
  });
});
