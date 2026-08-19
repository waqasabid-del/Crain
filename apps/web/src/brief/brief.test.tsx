import type { Brief } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AppLayout from "../app/(app)/layout.js";
import { BriefPage } from "../routes/BriefPage.js";
import { SettingsPage } from "../routes/SettingsPage.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";

/**
 * The brief, the theme, and the two product promises that live in this screen.
 *
 * *Every claim links to its source.* A claim rendered without a way to check it
 * is the product asking to be believed, which is the opposite of its pitch.
 *
 * *Certainty is categorical and never numeric.* md/05 §A.2.1 forbids a
 * percentage in the interface. These tests assert the absence of one, because
 * the failure is additive: nobody removes the tier badge, someone adds a number
 * next to it.
 */

const BRIEF: Brief = {
  periodStart: "2026-08-13T18:00:00Z",
  periodEnd: "2026-08-14T18:00:00Z",
  generatedAt: "2026-08-14T18:00:00Z",
  stored: true,
  suppressedCount: 0,
  truncated: false,
  narrative: "Rate limiting shipped. Staging credentials are still blocking verification.",
  abstained: false,
  claims: [
    {
      text: "Priya shipped rate limiting to production.",
      hedgedBySystem: false,
      resolvedActors: 0,
      unresolvedActors: 0,
      certainty: "verified",
      credits: ["Priya Nair"],
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
      hedgedBySystem: true,
      resolvedActors: 0,
      unresolvedActors: 0,
      certainty: "suggested",
      credits: [],
      // Deliberately unlinked: a meeting transcript has no permalink. An
      // unlinked citation is still provenance; a hidden one is not.
      citations: [{ evidenceId: "ev-standup-11", source: "meeting" }],
    },
  ],
};

function signedIn(brief: Brief | null = BRIEF): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    // The screen reads through the typed client now that the endpoint is in the
    // OpenAPI document. Stubbing `fetch` would exercise a request path that no
    // longer exists.
    getBrief: vi.fn(() =>
      brief === null ? Promise.reject(apiError(500)) : Promise.resolve(brief),
    ),
  });
}

describe("the brief", () => {
  it("shows every claim with a way to check it", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(), route: "/" },
    );

    // `getAllByText`: the sentence appears in the narrative and again as its
    // own claim. That is the design — the narrative is what a reader skims and
    // the claim list is what they check — so the query has to allow both.
    expect((await screen.findAllByText(/shipped rate limiting/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/staged rollout/i).length).toBeGreaterThan(0);

    // Linked evidence opens the source; unlinked evidence is still named.
    expect(screen.getByRole("link", { name: /ev-pr-482|github/i })).toHaveAttribute(
      "href",
      "https://github.com/acme/api/pull/482",
    );
    // The unlinked one is named but is not a link — provenance without a
    // permalink is still provenance, and hiding it would leave a hedged claim
    // with nothing behind it.
    const unlinked = screen.getAllByText(/ev-standup-11/i);
    expect(unlinked.length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /ev-standup-11/i })).not.toBeInTheDocument();
  });

  it("never renders a numeric confidence", async () => {
    // The interface is forbidden to display one (md/05 §A.2.1). A percentage
    // looks rigorous, means nothing to a non-technical reader, and invites the
    // false precision the categorical scale exists to avoid.

    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(), route: "/" },
    );

    const main = await screen.findByRole("main");
    await screen.findAllByText(/shipped rate limiting/i);

    expect(main.textContent).not.toMatch(/\d+\s*%/);
    expect(main.textContent).not.toMatch(/confidence[:=]?\s*0?\.\d+/i);
  });

  it("distinguishes an inferred claim from a verified one in text, not only in styling", async () => {
    // In a monochrome system the tier cannot be carried by colour, and a badge
    // alone is skimmed past. The hedge has to be in the sentence.

    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(), route: "/" },
    );

    expect((await screen.findAllByText(/it sounded like/i)).length).toBeGreaterThan(0);
  });

  it("says the period was quiet rather than showing an empty page", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      {
        client: signedIn({ ...BRIEF, claims: [], abstained: true, narrative: "" }),
        route: "/",
      },
    );

    // "Not enough to summarise" rather than "nothing happened". The two are
    // different answers, and a pipeline that declined to answer must not read
    // as a quiet week.
    const main = await screen.findByRole("main");
    expect(await within(main).findByText(/not enough to summarise/i)).toBeVisible();
  });

  it("explains a failure without blaming the reader", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(null), route: "/" },
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toBeVisible();
    // The failure is attributed to CAIRN, and a retry is offered. The first
    // version of this assertion looked for the substring "you did" and flagged
    // the copy "this is not something you did" — the exact sentence that makes
    // the message good. Assert the intent, not a keyword.
    expect(alert.textContent).toMatch(/cairn/i);
    expect(within(alert).getByRole("button", { name: /try again|retry/i })).toBeVisible();
  });
});

describe("the theme", () => {
  it("offers light, dark and system", async () => {
    // System is the default and must remain selectable: a reader who has set a
    // preference at the OS level has already answered this question.
    renderRoute(
      <AppLayout>
        <SettingsPage />
      </AppLayout>,
      { client: signedIn(), route: "/settings" },
    );

    const main = await screen.findByRole("main");
    for (const name of [/light/i, /dark/i, /system/i]) {
      expect(within(main).getByRole("radio", { name })).toBeInTheDocument();
    }
  });

  it("applies the reader's choice to the document", async () => {
    renderRoute(
      <AppLayout>
        <SettingsPage />
      </AppLayout>,
      { client: signedIn(), route: "/settings" },
    );

    const main = await screen.findByRole("main");
    await userEvent.click(within(main).getByRole("radio", { name: /dark/i }));

    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("leaves the choice to the operating system by default", async () => {
    // Stamping an explicit theme on first load overrides a preference the
    // reader already expressed, and it is the reason so many products ignore
    // system dark mode.
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(), route: "/" },
    );
    await screen.findByRole("main");

    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});

/**
 * The rail beside the brief: system panels, loaded independently. The two
 * promises here are isolation — a failed panel never takes the brief down —
 * and the boundary: the rail names sources and quotes statements, and welds no
 * number to any person.
 */
describe("the overview rail", () => {
  const FACT = {
    id: "fact-1",
    kind: "decision",
    statement: "The team decided to stage the payments cutover.",
    certainty: "verified" as const,
    resolvedActors: 0,
    unresolvedActors: 0,
    people: [],
    sources: [{ evidenceId: "ev-1", source: "meeting" }],
  };

  it("previews the latest activity with its provenance", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      {
        client: { ...signedIn(), listFacts: vi.fn(() => Promise.resolve({ items: [FACT] })) },
        route: "/",
      },
    );

    const rail = await screen.findByRole("complementary", { name: /around this brief/i });
    expect(await within(rail).findByText(/stage the payments cutover/i)).toBeVisible();
    expect(within(rail).getByText("meeting")).toBeVisible();
    expect(within(rail).getByRole("link", { name: /all activity/i })).toHaveAttribute(
      "href",
      "/feed",
    );
  });

  it("names the sources the record draws on", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      {
        client: {
          ...signedIn(),
          getFacets: vi.fn(() =>
            Promise.resolve({ people: [], projects: [], sources: ["github", "meeting"] }),
          ),
        },
        route: "/",
      },
    );

    const rail = await screen.findByRole("complementary", { name: /around this brief/i });
    expect(await within(rail).findByText("github")).toBeVisible();
    expect(within(rail).getByText(/how cairn treats this data/i)).toHaveAttribute("href", "/trust");
  });

  it("keeps the brief readable when a panel fails", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      {
        client: { ...signedIn(), listFacts: vi.fn(() => Promise.reject(apiError(500))) },
        route: "/",
      },
    );

    // The brief itself still renders in full…
    expect((await screen.findAllByText(/shipped rate limiting/i)).length).toBeGreaterThan(0);
    // …and the failure is contained to the panel, stated with a retry.
    const rail = screen.getByRole("complementary", { name: /around this brief/i });
    expect(await within(rail).findByText(/recent activity could not be loaded/i)).toBeVisible();
    expect(within(rail).getByRole("button", { name: /try again|retry/i })).toBeVisible();
  });

  it("says plainly when nothing has been recorded", async () => {
    renderRoute(
      <AppLayout>
        <BriefPage />
      </AppLayout>,
      { client: signedIn(), route: "/" },
    );

    const rail = await screen.findByRole("complementary", { name: /around this brief/i });
    expect(await within(rail).findByText(/nothing has been recorded yet/i)).toBeVisible();
    expect(within(rail).getByText(/no source has produced evidence yet/i)).toBeVisible();
  });
});
