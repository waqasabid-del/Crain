import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { ProjectDetailPage } from "../routes/ProjectDetailPage.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";

/**
 * The task board, and the line it must not cross.
 *
 * A board is the classic place scoring sneaks in — a count in a column header,
 * a card decorated with activity, a "top" anything. The tests that matter here
 * are the absences: headers that are exactly the state names, and a
 * vocabulary guard over the whole rendered board.
 */

const WORKSPACE = "22222222-2222-2222-2222-222222222222";

/** SESSION, with the one workspace held at a different role. */
function sessionAs(role: "member" | "viewer"): typeof SESSION {
  return { ...SESSION, workspaces: [{ ...SESSION.workspaces[0]!, role }] };
}

const DETAIL = {
  id: "p1",
  name: "Payments",
  purpose: "Card payments and the ledger behind them.",
  state: "active",
  stateDeclaredBy: "Ali Rahman",
  stateDeclaredAt: "2026-08-20T09:00:00Z",
  sources: [{ value: "acme/payments", addedBy: "Ali Rahman", addedAt: "2026-08-20T09:00:00Z" }],
  members: [
    {
      personId: "person-1",
      displayName: "Priya Nair",
      projectRole: "Backend",
      addedBy: "Ali Rahman",
      addedAt: "2026-08-20T09:00:00Z",
      removedBy: null as string | null,
      removedAt: null as string | null,
    },
  ],
  rollup: { delivered: [], blockers: [], openQuestions: [], decisions: [] },
};

const TASKS = [
  {
    id: "t1",
    projectId: "p1",
    title: "Ship rate limits",
    description: "",
    state: "todo",
    priority: "high",
    assigneePersonId: "person-1",
    assigneeName: "Priya Nair",
    dueOn: "2026-08-30",
    archivedAt: null,
    createdAt: "2026-08-20T09:00:00Z",
  },
  {
    id: "t2",
    projectId: "p1",
    title: "Rotate the signing keys",
    description: "",
    state: "in_review",
    priority: "normal",
    assigneePersonId: null,
    assigneeName: null,
    dueOn: null,
    archivedAt: null,
    createdAt: "2026-08-21T09:00:00Z",
  },
];

function boardClient(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    getProject: vi.fn(() => Promise.resolve(DETAIL)),
    listTasks: vi.fn(() => Promise.resolve({ tasks: TASKS })),
    ...overrides,
  });
}

function renderDetail(client: ReturnType<typeof createStubClient>): void {
  renderRoute(
    <AppLayout>
      <ProjectDetailPage projectId="p1" />
    </AppLayout>,
    { client, route: "/projects/p1" },
  );
}

async function findBoard(): Promise<HTMLElement> {
  const main = await screen.findByRole("main");
  return within(main).findByRole("region", { name: /^tasks$/i });
}

describe("a project's task board", () => {
  it("shows the five workflow columns in order, with each task in its own column", async () => {
    renderDetail(boardClient());

    const tasks = await findBoard();
    // Await data-produced content before reading structure.
    await within(tasks).findByRole("link", { name: "Ship rate limits" });

    const headers = within(tasks)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    // Exactly the state names, in workflow order — no counts, no decoration.
    expect(headers).toEqual(["To do", "In progress", "In review", "Blocked", "Done"]);

    const todo = within(tasks).getByRole("region", { name: "To do" });
    expect(within(todo).getByRole("link", { name: "Ship rate limits" })).toBeVisible();
    const review = within(tasks).getByRole("region", { name: "In review" });
    expect(within(review).getByRole("link", { name: "Rotate the signing keys" })).toBeVisible();
  });

  it("links each card to the task's own page under its title alone", async () => {
    renderDetail(boardClient());

    const tasks = await findBoard();
    const link = await within(tasks).findByRole("link", { name: "Ship rate limits" });
    expect(link).toHaveAttribute("href", "/tasks/t1");
  });

  it("shows the assignee by name and says Unassigned otherwise, never a count", async () => {
    renderDetail(boardClient());

    const tasks = await findBoard();
    await within(tasks).findByRole("link", { name: "Ship rate limits" });

    expect(within(tasks).getByText("Priya Nair")).toBeVisible();
    expect(within(tasks).getByText("Unassigned")).toBeVisible();
    // The vocabulary guard: nothing on the board scores, ranks or tallies.
    expect(tasks.textContent).not.toMatch(/\bscore|\brank|\bmost\b|\btop\b|productivity|velocity/i);
    expect(tasks.textContent).not.toMatch(/\d+ (tasks?|completed)/i);
  });

  it("offers no create control to a viewer", async () => {
    renderDetail(boardClient({ getSession: vi.fn(() => Promise.resolve(sessionAs("viewer"))) }));

    const tasks = await findBoard();
    await within(tasks).findByRole("link", { name: "Ship rate limits" });
    expect(within(tasks).queryByRole("button", { name: /new task/i })).toBeNull();
  });

  it("lets a member create a task and reloads the board with it", async () => {
    const user = userEvent.setup();
    const listTasks = vi
      .fn()
      .mockResolvedValueOnce({ tasks: [] })
      .mockResolvedValue({ tasks: TASKS });
    const createTask = vi.fn(() =>
      Promise.resolve({
        id: "t1",
        projectId: "p1",
        title: "Ship rate limits",
        description: "",
        state: "todo",
        priority: "high",
        createdAt: "2026-08-22T09:00:00Z",
      }),
    );
    renderDetail(
      boardClient({
        getSession: vi.fn(() => Promise.resolve(sessionAs("member"))),
        listTasks,
        createTask,
      }),
    );

    const tasks = await findBoard();
    // Empty board: the one honest line, with the control still offered.
    expect(await within(tasks).findByText("No tasks yet.")).toBeVisible();

    await user.click(within(tasks).getByRole("button", { name: "New task" }));
    await user.type(within(tasks).getByLabelText("Title"), "Ship rate limits");
    await user.type(within(tasks).getByLabelText("Description"), "Cap the burst rate.");
    await user.selectOptions(within(tasks).getByLabelText("Priority"), "high");
    await user.selectOptions(within(tasks).getByLabelText("Assignee"), "person-1");
    fireEvent.change(within(tasks).getByLabelText("Due date"), {
      target: { value: "2026-08-30" },
    });
    await user.click(within(tasks).getByRole("button", { name: "Create task" }));

    expect(await within(tasks).findByText(/was created/i)).toBeVisible();
    expect(createTask).toHaveBeenCalledWith(WORKSPACE, "p1", {
      title: "Ship rate limits",
      description: "Cap the burst rate.",
      priority: "high",
      // The panel creates ordinary work: the first column.
      state: "todo",
      assigneePersonId: "person-1",
      dueOn: "2026-08-30",
    });
    // The board re-read: the new card comes from the server, not a local patch.
    expect(await within(tasks).findByRole("link", { name: "Ship rate limits" })).toBeVisible();
    expect(listTasks).toHaveBeenCalledTimes(2);
  });

  it("surfaces a refused creation beside the form and keeps what was typed", async () => {
    const user = userEvent.setup();
    renderDetail(
      boardClient({
        getSession: vi.fn(() => Promise.resolve(sessionAs("member"))),
        createTask: vi.fn(() => Promise.reject(apiError(422))),
      }),
    );

    const tasks = await findBoard();
    await within(tasks).findByRole("link", { name: "Ship rate limits" });

    await user.click(within(tasks).getByRole("button", { name: "New task" }));
    await user.type(within(tasks).getByLabelText("Title"), "A task the API refuses");
    await user.click(within(tasks).getByRole("button", { name: "Create task" }));

    expect(await within(tasks).findByRole("alert")).toBeVisible();
    expect(within(tasks).getByLabelText("Title")).toHaveValue("A task the API refuses");
  });

  describe("the quick Add task composer", () => {
    /** The board as a member sees it, once its cards are on screen. */
    async function memberBoard(overrides = {}): Promise<HTMLElement> {
      renderDetail(
        boardClient({
          getSession: vi.fn(() => Promise.resolve(sessionAs("member"))),
          ...overrides,
        }),
      );
      const tasks = await findBoard();
      // Await content the data produced, never a region that exists while
      // loading.
      await within(tasks).findByRole("link", { name: "Ship rate limits" });
      return tasks;
    }

    function column(board: HTMLElement, name: string): HTMLElement {
      return within(board).getByRole("region", { name });
    }

    it("offers Add task at the foot of the four creatable columns, never Blocked", async () => {
      const board = await memberBoard();

      for (const name of ["To do", "In progress", "In review", "Done"]) {
        expect(
          within(column(board, name)).getByRole("button", { name: `Add task to ${name}` }),
        ).toBeVisible();
      }
      // Blocked is not creatable: a task is blocked by something that
      // happened to it, and the API refuses it 422.
      expect(
        within(column(board, "Blocked")).queryByRole("button", { name: /add task/i }),
      ).toBeNull();
    });

    it("opens the composer in the clicked column alone, with no project select", async () => {
      const board = await memberBoard();

      await userEvent.click(
        within(column(board, "In progress")).getByRole("button", {
          name: "Add task to In progress",
        }),
      );

      const composer = within(board).getByRole("form", { name: "Add task to In progress" });
      // The board belongs to one project, so nothing asks which.
      expect(within(composer).queryByRole("combobox", { name: "Project" })).toBeNull();
      expect(within(composer).getByRole("textbox", { name: "Title" })).toHaveFocus();
      expect(within(column(board, "To do")).queryByRole("form")).toBeNull();

      // Its assignee choice is this project's members.
      const assignee = within(composer).getByRole("combobox", { name: "Assignee" });
      expect(within(assignee).getByRole("option", { name: "Priya Nair" })).toBeVisible();
    });

    it("closes the first composer when a second is opened", async () => {
      const board = await memberBoard();

      await userEvent.click(
        within(column(board, "To do")).getByRole("button", { name: "Add task to To do" }),
      );
      await userEvent.click(
        within(column(board, "Done")).getByRole("button", { name: "Add task to Done" }),
      );

      expect(within(board).getByRole("form", { name: "Add task to Done" })).toBeVisible();
      expect(within(board).queryByRole("form", { name: "Add task to To do" })).toBeNull();
    });

    it("creates into each column's own state, with no project argument to choose", async () => {
      const createTask = vi.fn(() =>
        Promise.resolve({
          id: "t3",
          projectId: "p1",
          title: "Quick work",
          description: "",
          state: "todo",
          priority: "normal",
          createdAt: "2026-08-22T09:00:00Z",
        }),
      );
      const expected: [string, string][] = [
        ["To do", "todo"],
        ["In progress", "in_progress"],
        ["In review", "in_review"],
        ["Done", "done"],
      ];

      renderDetail(
        boardClient({
          getSession: vi.fn(() => Promise.resolve(sessionAs("member"))),
          createTask,
        }),
      );
      let board = await findBoard();
      await within(board).findByRole("link", { name: "Ship rate limits" });

      for (const [name, state] of expected) {
        board = await findBoard();
        // The board re-reads after each create: wait for its cards back.
        await within(board).findByRole("link", { name: "Ship rate limits" });
        await userEvent.click(
          within(column(board, name)).getByRole("button", { name: `Add task to ${name}` }),
        );
        const composer = within(board).getByRole("form", { name: `Add task to ${name}` });
        await userEvent.type(
          within(composer).getByRole("textbox", { name: "Title" }),
          `Work for ${name}`,
        );
        await userEvent.click(within(composer).getByRole("button", { name: "Add" }));

        expect(createTask).toHaveBeenLastCalledWith(WORKSPACE, "p1", {
          title: `Work for ${name}`,
          description: "",
          priority: "normal",
          state,
        });
      }
    });

    it("keeps Add disabled until a title is typed", async () => {
      const board = await memberBoard();

      await userEvent.click(within(board).getByRole("button", { name: "Add task to To do" }));
      const composer = within(board).getByRole("form", { name: "Add task to To do" });
      const add = within(composer).getByRole("button", { name: "Add" });
      expect(add).toBeDisabled();

      await userEvent.type(within(composer).getByRole("textbox", { name: "Title" }), "   ");
      expect(add).toBeDisabled();
      expect(within(composer).queryByRole("alert")).toBeNull();

      await userEvent.type(within(composer).getByRole("textbox", { name: "Title" }), "Real work");
      expect(add).toBeEnabled();
    });

    it("cancels on Escape and returns focus to the Add task control", async () => {
      const board = await memberBoard();

      await userEvent.click(within(board).getByRole("button", { name: "Add task to To do" }));
      const composer = within(board).getByRole("form", { name: "Add task to To do" });
      await userEvent.type(within(composer).getByRole("textbox", { name: "Title" }), "Never mind");
      await userEvent.keyboard("{Escape}");

      expect(within(board).queryByRole("form", { name: "Add task to To do" })).toBeNull();
      expect(within(board).getByRole("button", { name: "Add task to To do" })).toHaveFocus();
    });

    it("keeps the typed title and says why when the create is refused", async () => {
      const board = await memberBoard({ createTask: vi.fn(() => Promise.reject(apiError(422))) });

      await userEvent.click(within(board).getByRole("button", { name: "Add task to To do" }));
      const composer = within(board).getByRole("form", { name: "Add task to To do" });
      await userEvent.type(
        within(composer).getByRole("textbox", { name: "Title" }),
        "A task the API refuses",
      );
      await userEvent.click(within(composer).getByRole("button", { name: "Add" }));

      expect(await within(column(board, "To do")).findByRole("alert")).toBeVisible();
      expect(within(composer).getByRole("textbox", { name: "Title" })).toHaveValue(
        "A task the API refuses",
      );
    });

    it("clears the title and stays open after a create, and re-reads the board", async () => {
      const listTasks = vi.fn(() => Promise.resolve({ tasks: TASKS }));
      const board = await memberBoard({
        listTasks,
        createTask: vi.fn(() =>
          Promise.resolve({
            id: "t3",
            projectId: "p1",
            title: "One of several",
            description: "",
            state: "todo",
            priority: "normal",
            createdAt: "2026-08-22T09:00:00Z",
          }),
        ),
      });

      await userEvent.click(within(board).getByRole("button", { name: "Add task to To do" }));
      await userEvent.type(
        within(within(board).getByRole("form", { name: "Add task to To do" })).getByRole(
          "textbox",
          { name: "Title" },
        ),
        "One of several{Enter}",
      );

      await waitFor(() => {
        expect(listTasks).toHaveBeenCalledTimes(2);
      });
      // Queried afresh each time: the board is remounted by the re-read, so a
      // node captured before it is a detached node that can never hold focus.
      const titleNow = (): HTMLElement =>
        within(within(board).getByRole("form", { name: "Add task to To do" })).getByRole(
          "textbox",
          {
            name: "Title",
          },
        );
      await within(board).findByRole("form", { name: "Add task to To do" });
      await waitFor(() => {
        expect(titleNow()).toHaveValue("");
      });
      await waitFor(() => {
        expect(titleNow()).toHaveFocus();
      });
    });

    it("says nothing that counts, scores or ranks, composer included", async () => {
      const board = await memberBoard();

      await userEvent.click(within(board).getByRole("button", { name: "Add task to To do" }));
      expect(within(board).getByRole("form", { name: "Add task to To do" })).toBeVisible();

      expect(board.textContent).not.toMatch(
        /\bscore|\brank|\bmost\b|\btop\b|productivity|velocity/i,
      );
      expect(board.textContent).not.toMatch(/\d+ (tasks?|completed)/i);
    });

    it("offers a viewer no Add task control in any column", async () => {
      renderDetail(boardClient({ getSession: vi.fn(() => Promise.resolve(sessionAs("viewer"))) }));

      const board = await findBoard();
      await within(board).findByRole("link", { name: "Ship rate limits" });
      expect(within(board).queryByRole("button", { name: /add task/i })).toBeNull();
    });
  });

  it("keeps the hero and Team standing when only the task read fails", async () => {
    renderDetail(boardClient({ listTasks: vi.fn(() => Promise.reject(apiError(500))) }));

    const main = await screen.findByRole("main");
    const tasks = await within(main).findByRole("region", { name: /^tasks$/i });
    const alert = await within(tasks).findByRole("alert");
    expect(within(alert).getByRole("button", { name: /try again|retry/i })).toBeVisible();

    // The failure is the card's, never the page's.
    expect(within(main).getByRole("heading", { level: 1, name: "Payments" })).toBeVisible();
    const team = within(main).getByRole("region", { name: /^team$/i });
    expect(within(team).getByRole("link", { name: "Priya Nair" })).toBeVisible();
  });
});
