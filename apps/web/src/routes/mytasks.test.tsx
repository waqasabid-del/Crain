import type { MyTasks, ProjectList, TaskSummary } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { MyTasksPage } from "./MyTasksPage.js";

/**
 * My tasks: the reader's own work, grouped by column and never tallied.
 *
 * The assertions here are mostly about what the screen must *not* be. A
 * personal task list is the easiest place in the product to grow a scoreboard —
 * a count in a heading, a "you completed N", a velocity figure — so one test
 * holds the rendered text to the same vocabulary rule the dashboard and People
 * page are held to.
 */

function task(overrides: Partial<TaskSummary> & { id: string; title: string }): TaskSummary {
  return {
    state: "todo",
    priority: "normal",
    projectId: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    createdAt: "2026-08-10T09:00:00Z",
    description: "",
    ...overrides,
  };
}

const EMPTY: MyTasks = { todo: [], inProgress: [], inReview: [], blocked: [], done: [] };

const TASKS: MyTasks = {
  inProgress: [
    task({
      id: "11111111-1111-1111-1111-111111111111",
      title: "Wire the export",
      state: "in_progress",
      priority: "high",
      dueOn: "2026-08-28",
    }),
  ],
  inReview: [
    task({
      id: "22222222-2222-2222-2222-222222222222",
      title: "Review the schema",
      state: "in_review",
    }),
  ],
  blocked: [
    task({
      id: "33333333-3333-3333-3333-333333333333",
      title: "Unblock the webhook",
      state: "blocked",
    }),
  ],
  todo: [task({ id: "44444444-4444-4444-4444-444444444444", title: "Draft the notice" })],
  done: [
    task({ id: "55555555-5555-5555-5555-555555555555", title: "Ship the audit", state: "done" }),
  ],
};

const PROJECTS: ProjectList = {
  projects: [{ id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", name: "Atlas", state: "active" }],
};

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMyTasks: vi.fn(() => Promise.resolve(TASKS)),
    listProjects: vi.fn(() => Promise.resolve(PROJECTS)),
    ...overrides,
  });
}

function renderPage(stub = client()): void {
  renderRoute(
    <AppLayout>
      <MyTasksPage />
    </AppLayout>,
    { client: stub, route: "/tasks" },
  );
}

describe("my tasks", () => {
  it("renders the groups in workflow order, with their tasks", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    // Await content the data produced, never a region that exists while
    // loading — the loading skeleton has no headings, so the headings are safe
    // only once a task title is present.
    await within(main).findByText("Wire the export");

    const headings = within(main)
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["In progress", "In review", "Blocked", "To do", "Recently done"]);

    expect(within(main).getByText("Review the schema")).toBeVisible();
    expect(within(main).getByText("Unblock the webhook")).toBeVisible();
    expect(within(main).getByText("Draft the notice")).toBeVisible();
    expect(within(main).getByText("Ship the audit")).toBeVisible();
  });

  it("links each task to its own page", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    const link = await within(main).findByRole("link", { name: "Wire the export" });
    expect(link).toHaveAttribute("href", "/tasks/11111111-1111-1111-1111-111111111111");
  });

  it("shows the project's name, the priority as a word, and the due date", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");

    // Every stubbed task belongs to Atlas, so the name appears once per row.
    expect(within(main).getAllByText("Atlas").length).toBeGreaterThan(0);
    expect(within(main).getByText("High")).toBeVisible();
    expect(within(main).getByText(/due/i)).toBeVisible();
  });

  it("does not render an empty group at all", async () => {
    renderPage(
      client({
        listMyTasks: vi.fn(() =>
          Promise.resolve({
            ...EMPTY,
            todo: [task({ id: "44444444-4444-4444-4444-444444444444", title: "Draft the notice" })],
          }),
        ),
      }),
    );

    const main = await screen.findByRole("main");
    await within(main).findByText("Draft the notice");

    expect(within(main).queryByRole("heading", { name: "In progress" })).toBeNull();
    expect(within(main).queryByRole("heading", { name: "Recently done" })).toBeNull();
    const headings = within(main)
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual(["To do"]);
  });

  it("shows one calm empty state when every group is empty", async () => {
    // Also the shape a caller with no Person row receives: the API answers
    // empty groups rather than an error, and the screen treats it as ordinary.
    renderPage(client({ listMyTasks: vi.fn(() => Promise.resolve(EMPTY)) }));

    const main = await screen.findByRole("main");
    expect(await within(main).findByText("Nothing is assigned to you right now.")).toBeVisible();
    expect(within(main).queryByRole("heading", { name: "In progress" })).toBeNull();
    expect(within(main).queryByRole("alert")).toBeNull();
  });

  it("announces loading while the tasks are on their way", async () => {
    renderPage(
      client({
        listMyTasks: vi.fn(
          () =>
            new Promise<MyTasks>(() => {
              // Never resolves: the screen stays in its loading state.
            }),
        ),
      }),
    );

    const main = await screen.findByRole("main");
    const status = await within(main).findByRole("status");
    expect(status).toHaveTextContent(/loading your tasks/i);
  });

  it("offers a retry after a failure, and recovers", async () => {
    const listMyTasks = vi.fn().mockRejectedValueOnce(apiError(500)).mockResolvedValue(TASKS);
    renderPage(client({ listMyTasks }));

    const main = await screen.findByRole("main");
    const alert = await within(main).findByRole("alert");
    expect(alert).toHaveTextContent(/could not be loaded/i);

    await userEvent.click(within(main).getByRole("button", { name: /try again/i }));
    expect(await within(main).findByText("Wire the export")).toBeVisible();
  });

  it("asks the reader to join a workspace when they belong to none", async () => {
    renderPage(
      client({
        getSession: vi.fn(() => Promise.resolve({ ...SESSION, workspaces: [] })),
        listMyTasks: vi.fn(() => Promise.reject(new Error("must not be called"))),
        listProjects: vi.fn(() => Promise.reject(new Error("must not be called"))),
      }),
    );

    const main = await screen.findByRole("main");
    expect(await within(main).findByText(/join a workspace to see your tasks/i)).toBeVisible();
    expect(within(main).queryByRole("alert")).toBeNull();
  });

  it("never counts, scores or measures the person whose tasks these are", async () => {
    renderPage();

    const main = await screen.findByRole("main");
    await within(main).findByText("Wire the export");
    const text = main.textContent;

    // No per-person count phrasing: the heading is "In progress", never
    // "3 in progress", and nothing says "you completed N".
    expect(text).not.toMatch(/\d+\s*(tasks?|completed|done)/i);
    // The vocabulary, including in negation — same rule as the dashboard.
    expect(text).not.toMatch(
      /\b(?:top|most|least|rank\w*|score\w*|leaderboard|productivity|performance|velocity)\b/i,
    );
    expect(text).not.toMatch(/\d+\s?%/);
  });
});
