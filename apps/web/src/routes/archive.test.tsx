import type { Brief, BriefArchive } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { ArchivedBriefPage } from "./ArchivedBriefPage.js";
import { ArchivePage, formatPeriod } from "./ArchivePage.js";
import { BriefPage } from "./BriefPage.js";

/**
 * Step 21's exit criterion, and the property that makes an archive worth having.
 *
 * **Every claim links to its source in one click.** The first block below is
 * that, and it is the assertion that would have failed before this step:
 * citations used to be bare identifiers, which satisfies "every claim carries a
 * citation" and fails what a citation is *for*.
 *
 * **An archive entry does not change when it is read.** A brief is something
 * the product said to a team. The API enforces that by writing a finished
 * period once; this screen is the reason it matters, so the tests here assert
 * that opening a past brief reads rather than regenerates.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`. Contrast is measured in
  // `packages/ui`, where a real canvas exists.
  rules: { "color-contrast": { enabled: false } },
} as const;

const BRIEF: Brief = {
  id: "88888888-8888-8888-8888-888888888888",
  periodStart: "2026-08-12T06:00:00Z",
  periodEnd: "2026-08-13T06:00:00Z",
  generatedAt: "2026-08-13T06:00:00Z",
  stored: true,
  abstained: false,
  suppressedCount: 0,
  truncated: false,
  narrative: "Rate limiting shipped. The payments cutover still needs a staged rollout.",
  claims: [
    {
      text: "Priya shipped rate limiting to production.",
      certainty: "verified",
      hedgedBySystem: false,
      resolvedActors: 0,
      unresolvedActors: 0,
      credits: ["Priya Nair"],
      factIds: ["11111111-1111-1111-1111-111111111111"],
      citations: [
        {
          evidenceId: "ev-pr-482",
          source: "github",
          url: "https://github.com/acme/api/pull/482",
        },
      ],
    },
    {
      text: "It sounded like the payments cutover will need a staged rollout.",
      certainty: "suggested",
      hedgedBySystem: true,
      resolvedActors: 0,
      unresolvedActors: 0,
      credits: [],
      factIds: ["22222222-2222-2222-2222-222222222222"],
      // No permalink: a meeting transcript has none. The citation is still
      // shown, because an unlinked source is provenance and a hidden one is not.
      citations: [{ evidenceId: "ev-standup-11", source: "meeting" }],
    },
  ],
};

const ARCHIVE: BriefArchive = {
  items: [
    {
      id: "88888888-8888-8888-8888-888888888888",
      periodStart: "2026-08-12T06:00:00Z",
      periodEnd: "2026-08-13T06:00:00Z",
      generatedAt: "2026-08-13T06:00:00Z",
      excerpt: "Rate limiting shipped. The payments cutover still needs a staged rollout.",
      claimCount: 2,
      abstained: false,
    },
    {
      id: "99999999-9999-9999-9999-999999999999",
      periodStart: "2026-08-11T06:00:00Z",
      periodEnd: "2026-08-12T06:00:00Z",
      generatedAt: "2026-08-12T06:00:00Z",
      excerpt: "",
      claimCount: 0,
      abstained: true,
    },
  ],
};

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    ...overrides,
  });
}

describe("one click to the source", () => {
  it("links every claim that has a permalink", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: client({ getBrief: vi.fn(() => Promise.resolve(BRIEF)) }), route: "/" },
    );

    // The sentence appears in the narrative and again as its own claim.
    await screen.findAllByText(/shipped rate limiting/i);

    // The citations sit in a `<details>` that starts collapsed — printing eight
    // links under every sentence would bury the narrative. "One click" is the
    // promise, and this is the click.
    // Clicked by its accessible name rather than by role: a `<summary>` has no
    // mapped role in jsdom, and the name is what a screen-reader user hears —
    // "Sources for: Priya shipped rate limiting to production." rather than a
    // page of identical "1 source" controls.
    const [firstToggle] = screen.getAllByRole("group");
    await userEvent.click(within(firstToggle!).getByText(/Sources for:/));

    const link = await screen.findByRole("link", { name: /ev-pr-482/i });
    expect(link).toHaveAttribute("href", "https://github.com/acme/api/pull/482");
    // Evidence lives outside this app; opening in place would lose the brief
    // the reader is halfway through.
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("still shows a source that has no permalink", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: client({ getBrief: vi.fn(() => Promise.resolve(BRIEF)) }), route: "/" },
    );

    await screen.findAllByText(/staged rollout/i);
    const toggles = screen.getAllByRole("group");
    await userEvent.click(within(toggles[1]!).getByText(/Sources for:/));

    expect(await screen.findByText(/ev-standup-11/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /ev-standup-11/ })).not.toBeInTheDocument();
  });
});

describe("the archive", () => {
  it("lists past briefs, newest first, each linking to its own address", async () => {
    renderRoute(
      <AppLayout>
        <ArchivePage />
      </AppLayout>,
      { client: client({ listBriefs: vi.fn(() => Promise.resolve(ARCHIVE)) }), route: "/archive" },
    );

    const list = await screen.findByRole("list", { name: /past briefs/i });
    const links = within(list).getAllByRole("link");

    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute("href", "/archive/88888888-8888-8888-8888-888888888888");
  });

  it("says a quiet period was quiet rather than showing an empty row", async () => {
    // An abstention has no excerpt, and a blank row reads as a rendering bug
    // rather than as the system declining to guess.
    renderRoute(
      <AppLayout>
        <ArchivePage />
      </AppLayout>,
      { client: client({ listBriefs: vi.fn(() => Promise.resolve(ARCHIVE)) }), route: "/archive" },
    );

    expect(await screen.findByText(/did not find enough in this period/i)).toBeVisible();
  });

  it("explains an empty archive without implying something is broken", async () => {
    renderRoute(
      <AppLayout>
        <ArchivePage />
      </AppLayout>,
      {
        client: client({ listBriefs: vi.fn(() => Promise.resolve({ items: [] })) }),
        route: "/archive",
      },
    );

    expect(await screen.findByRole("heading", { name: /no briefs yet/i })).toBeVisible();
    expect(screen.getByText(/appears here tomorrow/i)).toBeVisible();
  });

  it("reads a past brief rather than regenerating it", async () => {
    // The property the whole archive rests on. `getArchivedBrief` reads a
    // record; `getBrief` would compose a new one from facts that may have been
    // corrected since — which would quietly rewrite what the team was told.
    const getArchivedBrief = vi.fn(() => Promise.resolve(BRIEF));
    const getBrief = vi.fn(() => Promise.resolve(BRIEF));

    renderRoute(
      <AppLayout>
        <ArchivedBriefPage briefId="88888888-8888-8888-8888-888888888888" />
      </AppLayout>,
      {
        client: client({ getArchivedBrief, getBrief }),
        route: "/archive/88888888-8888-8888-8888-888888888888",
      },
    );

    // The sentence appears in the narrative and again as its own claim.
    await screen.findAllByText(/shipped rate limiting/i);
    expect(getArchivedBrief).toHaveBeenCalledWith(
      SESSION.workspaces[0]?.workspace.id,
      "88888888-8888-8888-8888-888888888888",
      expect.anything(),
    );
    expect(getBrief).not.toHaveBeenCalled();
  });

  it("explains a brief that cannot be loaded, with a way back", async () => {
    renderRoute(
      <AppLayout>
        <ArchivedBriefPage briefId="00000000-0000-0000-0000-000000000000" />
      </AppLayout>,
      {
        client: client({ getArchivedBrief: vi.fn(() => Promise.reject(apiError(404))) }),
        route: "/archive/00000000-0000-0000-0000-000000000000",
      },
    );

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("link", { name: /all briefs/i })).toHaveAttribute("href", "/archive");
  });

  it("passes an axe audit", async () => {
    const { container } = renderRoute(
      <AppLayout>
        <ArchivePage />
      </AppLayout>,
      { client: client({ listBriefs: vi.fn(() => Promise.resolve(ARCHIVE)) }), route: "/archive" },
    );
    await screen.findByRole("list", { name: /past briefs/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("formatPeriod", () => {
  it("shows a single date for a one-day period", () => {
    // "12 August" is a date somebody recognises. "12 August 06:00 – 13 August
    // 06:00" is a range they have to parse to learn the same thing.
    const formatted = formatPeriod("2026-08-12T06:00:00Z", "2026-08-13T06:00:00Z");
    expect(formatted).not.toContain("–");
  });

  it("shows a range for a longer period", () => {
    const formatted = formatPeriod("2026-08-05T06:00:00Z", "2026-08-12T06:00:00Z");
    expect(formatted).toContain("–");
  });
});
