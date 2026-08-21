import { screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { DashboardPage } from "./DashboardPage.js";
import { ProjectDetailPage } from "./ProjectDetailPage.js";
import { ProjectsPage } from "./ProjectsPage.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";

/**
 * The dashboard, and the line it must not cross.
 *
 * Every figure on the Overview counts *work* — blockers, deliveries, questions,
 * projects. The tests that matter here are the ones asserting what is absent:
 * no ranking vocabulary, no number welded to a person's name, no invented
 * completion figure. The failure mode is additive — nobody deletes the
 * boundary, somebody adds a count beside a name — so the guards are written as
 * absences over the whole rendered page.
 */

const AXE = { rules: { "color-contrast": { enabled: false } } } as const;

const FACT = {
  id: "f1",
  kind: "delivery",
  statement: "Rate limiting shipped to production.",
  certainty: "verified" as const,
  origin: "extracted" as const,
  validFrom: "2026-08-19T09:00:00Z",
  occurredAt: "2026-08-19T09:00:00Z",
  resolvedActors: 0,
  unresolvedActors: 0,
  people: [{ mention: "Priya Nair" }],
  sources: [
    { evidenceId: "ev-482", source: "github", url: "https://github.com/acme/api/pull/482" },
  ],
};

const PROJECT = {
  id: "p1",
  name: "Payments",
  purpose: "Card payments and the ledger behind them.",
  state: "active",
  stateDeclaredAt: "2026-08-20T09:00:00Z",
};

const MEMBER = {
  userId: "user-1",
  personId: "person-1",
  email: "ali@example.com",
  displayName: "Ali Rahman",
  role: "owner" as const,
  capacity: "not_stated" as const,
  joinedAt: "2026-01-04T09:00:00Z",
};

function dashboardClient(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMembers: vi.fn(() => Promise.resolve([MEMBER])),
    listProjects: vi.fn(() => Promise.resolve({ projects: [PROJECT] })),
    listFacts: vi.fn(() => Promise.resolve({ items: [FACT] })),
    ...overrides,
  });
}

describe("the dashboard", () => {
  it("shows every team member with their role", async () => {
    renderRoute(
      <AppLayout>
        <DashboardPage />
      </AppLayout>,
      { client: dashboardClient(), route: "/" },
    );

    const main = await screen.findByRole("main");
    // The Card's region exists while its body is still loading, so awaiting
    // the region proves nothing - wait for what the data actually produces.
    const link = await within(main).findByRole("link", { name: "Ali Rahman" });
    expect(link).toHaveAttribute("href", "/people/person-1");
    const team = within(main).getByRole("region", { name: /^team$/i });
    expect(within(team).getByText("Owner")).toBeVisible();
  });

  it("shows every project, each opening its own page", async () => {
    renderRoute(
      <AppLayout>
        <DashboardPage />
      </AppLayout>,
      { client: dashboardClient(), route: "/" },
    );

    const main = await screen.findByRole("main");
    expect(await within(main).findByRole("link", { name: /payments/i })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
  });

  it("leaves a member without a person record as plain text, not a dead link", async () => {
    renderRoute(
      <AppLayout>
        <DashboardPage />
      </AppLayout>,
      {
        client: dashboardClient({
          listMembers: vi.fn(() =>
            Promise.resolve([{ ...MEMBER, personId: null, displayName: "Jo Blake" }]),
          ),
        }),
        route: "/",
      },
    );

    const main = await screen.findByRole("main");
    const name = await within(main).findByText("Jo Blake");
    expect(name).toBeVisible();
    expect(within(main).queryByRole("link", { name: "Jo Blake" })).toBeNull();
  });

  it("never ranks, scores or measures the people on it", async () => {
    renderRoute(
      <AppLayout>
        <DashboardPage />
      </AppLayout>,
      { client: dashboardClient(), route: "/" },
    );

    const main = await screen.findByRole("main");
    // Wait for loaded content, not for the card that frames it.
    await within(main).findByRole("link", { name: "Ali Rahman" });
    const text = main.textContent;

    // The vocabulary, including in negation: this product's People page
    // rejects even a disclaimer, and the dashboard is held to the same rule.
    expect(text).not.toMatch(
      /\b(?:top|most|least|rank\w*|score\w*|leaderboard|productivity|performance|velocity)\b/i,
    );
    // No percentage and no bare count beside a person.
    expect(text).not.toMatch(/\d+\s?%/);
  });

  it("keeps one section readable when the other fails", async () => {
    renderRoute(
      <AppLayout>
        <DashboardPage />
      </AppLayout>,
      {
        client: dashboardClient({ listProjects: vi.fn(() => Promise.reject(apiError(500))) }),
        route: "/",
      },
    );

    const main = await screen.findByRole("main");
    expect(await within(main).findAllByRole("alert")).not.toHaveLength(0);
    // The other section still rendered its data.
    expect(await within(main).findByRole("link", { name: "Ali Rahman" })).toBeVisible();
  });

  it("passes an axe audit", async () => {
    const { container } = renderRoute(
      <AppLayout>
        <DashboardPage />
      </AppLayout>,
      { client: dashboardClient(), route: "/" },
    );
    await screen.findByRole("link", { name: "Ali Rahman" });

    expect(await axe(container, AXE)).toHaveNoViolations();
  });
});

describe("the projects portfolio", () => {
  it("lists projects with their declared state", async () => {
    renderRoute(
      <AppLayout>
        <ProjectsPage />
      </AppLayout>,
      { client: dashboardClient(), route: "/projects" },
    );

    const main = await screen.findByRole("main");
    expect(await within(main).findByRole("link", { name: "Payments" })).toHaveAttribute(
      "href",
      "/projects/p1",
    );
    expect(within(main).getByLabelText(/project state: active/i)).toBeVisible();
  });

  it("says who declared a state, and says so when nobody has", async () => {
    renderRoute(
      <AppLayout>
        <ProjectsPage />
      </AppLayout>,
      {
        client: dashboardClient({
          listProjects: vi.fn(() =>
            Promise.resolve({
              projects: [{ id: "p2", name: "Ledger", state: "unknown" }],
            }),
          ),
        }),
        route: "/projects",
      },
    );

    const main = await screen.findByRole("main");
    // "Not set up yet" comes from the tile itself, so awaiting it proves the
    // data arrived. ("Not declared" is also a filter link, present at once.)
    expect(await within(main).findByText(/not set up yet/i)).toBeVisible();
    expect(within(main).getByLabelText(/project state: not declared/i)).toBeVisible();
  });

  it("offers an empty state with a way out when a filter matches nothing", async () => {
    renderRoute(
      <AppLayout>
        <ProjectsPage />
      </AppLayout>,
      {
        client: dashboardClient({ listProjects: vi.fn(() => Promise.resolve({ projects: [] })) }),
        route: "/projects",
        search: "state=blocked",
      },
    );

    const main = await screen.findByRole("main");
    expect(await within(main).findByText(/no projects in that state/i)).toBeVisible();
    expect(within(main).getByRole("link", { name: /show every project/i })).toBeVisible();
  });
});

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
  rollup: {
    delivered: [
      {
        statement: "Rate limiting shipped to production.",
        certainty: "verified",
        occurredAt: "2026-08-19T09:00:00Z",
        sources: [{ evidenceId: "ev-482", source: "github", url: "https://github.com/x/y/pull/1" }],
      },
    ],
    blockers: [],
    openQuestions: [],
    decisions: [],
  },
};

describe("a project's detail", () => {
  function detailClient(project = DETAIL): ReturnType<typeof createStubClient> {
    return createStubClient({
      getSession: vi.fn(() => Promise.resolve(SESSION)),
      getProject: vi.fn(() => Promise.resolve(project)),
    });
  }

  it("shows delivered work with a citation that opens the source", async () => {
    renderRoute(
      <AppLayout>
        <ProjectDetailPage projectId="p1" />
      </AppLayout>,
      { client: detailClient(), route: "/projects/p1" },
    );

    const main = await screen.findByRole("main");
    const delivered = await within(main).findByRole("region", { name: /delivered work/i });
    expect(within(delivered).getByText(/rate limiting shipped/i)).toBeVisible();
    expect(within(delivered).getByRole("link", { name: /ev-482/i })).toHaveAttribute(
      "href",
      "https://github.com/x/y/pull/1",
    );
  });

  it("states plainly that planned work is not tracked, instead of inventing a figure", async () => {
    renderRoute(
      <AppLayout>
        <ProjectDetailPage projectId="p1" />
      </AppLayout>,
      { client: detailClient(), route: "/projects/p1" },
    );

    const main = await screen.findByRole("main");
    const planned = await within(main).findByRole("region", {
      name: /in progress and planned work/i,
    });
    expect(within(planned).getByText(/does not track planned work/i)).toBeVisible();
    // The honest absence, not a placeholder metric.
    expect(planned.textContent).not.toMatch(/\d+\s?%/);
  });

  it("lists membership as context, with who added whom and nothing measured", async () => {
    renderRoute(
      <AppLayout>
        <ProjectDetailPage projectId="p1" />
      </AppLayout>,
      { client: detailClient(), route: "/projects/p1" },
    );

    const main = await screen.findByRole("main");
    const people = await within(main).findByRole("region", { name: /^people$/i });
    expect(within(people).getByText("Priya Nair")).toBeVisible();
    expect(within(people).getByText("Backend")).toBeVisible();
    expect(within(people).getByText(/added by ali rahman/i)).toBeVisible();
    // No number is attached to the person anywhere in the section.
    expect(
      within(people).queryByText(/\b\d+\s+(?:facts?|commits?|deliveries|updates?)\b/i),
    ).toBeNull();
  });

  it("keeps a removed member visible as closed history", async () => {
    renderRoute(
      <AppLayout>
        <ProjectDetailPage projectId="p1" />
      </AppLayout>,
      {
        client: detailClient({
          ...DETAIL,
          members: [
            {
              ...DETAIL.members[0]!,
              removedBy: "Ali Rahman",
              removedAt: "2026-08-21T09:00:00Z",
            },
          ],
        }),
        route: "/projects/p1",
      },
    );

    const main = await screen.findByRole("main");
    const people = await within(main).findByRole("region", { name: /^people$/i });
    // Still listed: a shrinking list that drops people reads as a project that
    // never had them.
    expect(within(people).getByText("Priya Nair")).toBeVisible();
    expect(within(people).getByText(/removed by ali rahman/i)).toBeVisible();
  });

  it("offers a retry and a way back when the project cannot be loaded", async () => {
    renderRoute(
      <AppLayout>
        <ProjectDetailPage projectId="p1" />
      </AppLayout>,
      {
        client: createStubClient({
          getSession: vi.fn(() => Promise.resolve(SESSION)),
          getProject: vi.fn(() => Promise.reject(apiError(404))),
        }),
        route: "/projects/p1",
      },
    );

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("button", { name: /try again|retry/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /back to all projects/i })).toBeVisible();
  });

  it("passes an axe audit", async () => {
    const { container } = renderRoute(
      <AppLayout>
        <ProjectDetailPage projectId="p1" />
      </AppLayout>,
      { client: detailClient(), route: "/projects/p1" },
    );
    await screen.findByText(/rate limiting shipped/i);

    expect(await axe(container, AXE)).toHaveNoViolations();
  });
});
