import type { FactPage } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, SESSION } from "../test/harness.js";
import { MyWeekPage } from "./MyWeekPage.js";

/**
 * My Week, and the correction that makes it the reader's record.
 *
 * The assertions here are mostly about what the screen must *not* be. md/05
 * §B.1 puts CAIRN close to the line between coordination software and workplace
 * monitoring, and a personal page is where that line is easiest to cross: a
 * count, a streak, a comparison with a colleague, and the product has become the
 * thing its positioning forbids. So one test checks for numbers that should not
 * be there, and one checks that correcting is a single action rather than a form
 * somebody has to be motivated to fill in.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

type Fact = NonNullable<FactPage["items"]>[number];

const FACT: Fact = {
  id: "11111111-1111-1111-1111-111111111111",
  kind: "delivery",
  statement: "Priya shipped rate limiting to production.",
  certainty: "observed",
  origin: "extracted",
  validFrom: "2026-08-10T09:00:00Z",
  occurredAt: "2026-08-10T09:00:00Z",
  people: [{ mention: "Priya Nair" }],
  // The default is the fourth attribution state: nothing to attribute beyond
  // the named mention, and therefore nothing for the screen to say.
  resolvedActors: 0,
  unresolvedActors: 0,
  sources: [
    {
      evidenceId: "ev-pr-482",
      source: "github",
      url: "https://github.com/acme/api/pull/482",
    },
  ],
};

const WEEK: FactPage = { items: [FACT] };

/** The same fact with different attribution behind it. */
function weekWith(counts: { resolvedActors: number; unresolvedActors: number }): FactPage {
  return { items: [{ ...FACT, ...counts }] };
}

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    myWeek: vi.fn(() => Promise.resolve(WEEK)),
    ...overrides,
  });
}

function render(stub = client()): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <MyWeekPage />
    </AppLayout>,
    { client: stub, route: "/me" },
  );
}

describe("the reader's own record", () => {
  it("shows what CAIRN believes, with somewhere to check it", async () => {
    render();

    // Twice by design: once as the claim, once inside the correction button's
    // accessible name, which is what tells one "Not right?" from another.
    expect((await screen.findAllByText(/shipped rate limiting/i)).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /ev-pr-482/ })).toHaveAttribute(
      "href",
      "https://github.com/acme/api/pull/482",
    );
  });

  it("carries no count, streak or comparison", async () => {
    // The line between coordination software and monitoring is crossed by a
    // number on a personal page, not by a policy change. This is the test that
    // notices somebody adding "4 things this week" because it looked friendly.
    render();
    await screen.findAllByText(/shipped rate limiting/i);

    const main = await screen.findByRole("main");
    const text = main.textContent;

    // Tallies of a person's output.
    expect(text).not.toMatch(/\b\d+\s+(?:things|items|contributions|commits|facts)\b/i);

    // Comparison *between people*, which is the actual prohibition. The first
    // version of this matched "corroborated across more than one source" — the
    // certainty badge's own copy — and would have failed for the one reason
    // that has nothing to do with monitoring. A bare "more than" is a phrase;
    // "more than the team" is a ranking.
    expect(text).not.toMatch(/\bstreak\b/i);
    expect(text).not.toMatch(/\brank(?:ed|ing)?\b/i);
    expect(text).not.toMatch(/\b(?:productivity|performance)\s+(?:score|rating|index)\b/i);
    expect(text).not.toMatch(/\bmore\s+than\s+(?:\w+\s+)?(?:colleagues|others|the team|anyone)\b/i);
    expect(text).not.toMatch(/\b(?:top|bottom|best|worst)\s+(?:performer|contributor)/i);
  });

  it("explains an empty week without implying the reader did nothing", async () => {
    // The overwhelmingly likely cause is an unmatched commit address, not an
    // idle week — and telling somebody they did nothing when the truth is that
    // CAIRN cannot see them is the worst available failure on this screen.
    render(client({ myWeek: vi.fn(() => Promise.resolve({ items: [] })) }));

    expect(await screen.findByRole("heading", { name: /nothing about you yet/i })).toBeVisible();
    expect(screen.getByText(/address on your commits/i)).toBeVisible();
  });
});

/**
 * Attribution, and the four things a record can honestly say about who is
 * behind a statement.
 *
 * The counts exist because the alternative was silence. The links underneath
 * carry Slack `U…` and Google Chat `users/…` ids — private provider handles the
 * API strips out of `people` altogether — and dropping them without trace
 * leaves this screen unable to tell "nobody else was involved" from "somebody
 * was, and CAIRN cannot yet say who". To a person checking whether their own
 * record is complete, those are opposite answers.
 *
 * So the tests here are about wording as much as rendering. The unresolved case
 * is one sentence away from reading as a defect the reader caused, or as a
 * colleague hiding, and either version teaches people to distrust the record
 * instead of finishing it.
 */
describe("who is behind a statement", () => {
  it("says nothing when there is nothing to attribute", async () => {
    // The fourth state. A line reading "no connected accounts" would invent a
    // status the product does not have, on the screen least able to afford one.
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 0, unresolvedActors: 0 }))),
      }),
    );
    await screen.findAllByText(/shipped rate limiting/i);

    const main = await screen.findByRole("main");
    expect(main.textContent).not.toMatch(/connected account/i);
    expect(main.textContent).not.toMatch(/has not connected/i);
  });

  it("says in words when a connected identity is behind it, and never which", async () => {
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 1, unresolvedActors: 0 }))),
      }),
    );

    expect(await screen.findByText(/attributed through a connected account/i)).toBeVisible();
  });

  it("counts connected accounts in words rather than as a figure", async () => {
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 3, unresolvedActors: 0 }))),
      }),
    );

    expect(await screen.findByText(/attributed through three connected accounts/i)).toBeVisible();
  });

  it("states an unresolved identity as a fact, not as something the reader broke", async () => {
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 0, unresolvedActors: 1 }))),
      }),
    );

    const note = await screen.findByText(/one contributor here has not connected their account/i);
    expect(note).toBeVisible();

    // The wording test that matters. "CAIRN could not identify a contributor"
    // is the same information and the wrong sentence: it makes an ordinary,
    // temporary state of the identity graph sound like a failure with a cause,
    // and the reader — who did nothing — is the one reading it.
    const text = note.textContent;
    expect(text).not.toMatch(/error|failed|failure|problem|invalid|unable|broken|denied/i);
    // Nor may it imply concealment: nobody here is withholding anything.
    expect(text).not.toMatch(/hidden|hiding|anonymous|withheld|refused|unknown person/i);
  });

  it("pluralises without turning the sentence into a readout", async () => {
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 0, unresolvedActors: 2 }))),
      }),
    );

    expect(
      await screen.findByText(/two contributors here have not connected their accounts/i),
    ).toBeVisible();
  });

  it("offers the reader their own way out, and it is operable from the keyboard", async () => {
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 0, unresolvedActors: 1 }))),
      }),
    );

    const link = await screen.findByRole("link", { name: /connect your own accounts/i });
    expect(link).toHaveAttribute("href", "/settings");

    // Reachable by tab, which is the whole of "operable" for a link. A note
    // whose only remedy needs a mouse is a note with no remedy.
    link.focus();
    expect(link).toHaveFocus();
    await userEvent.tab();
    expect(link).not.toHaveFocus();
  });

  it("renders no provider account id or address anywhere in the markup", async () => {
    // The hard rule. The API sends counts and nothing else; this fails if a
    // screen ever starts deriving a handle from something it was given.
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 2, unresolvedActors: 2 }))),
      }),
    );
    await screen.findAllByText(/shipped rate limiting/i);

    // The record itself rather than the whole container: the shell shows the
    // reader their own signed-in address, which is theirs to see. What must
    // never appear is somebody else's, or a provider's handle for anybody.
    const record = screen.getByRole("list", { name: /what cairn believes about you/i });
    const html = record.innerHTML;
    // Slack member ids, Google Chat member resources, and anything shaped like
    // an address.
    expect(html).not.toMatch(/\bU[A-Z0-9]{6,}\b/);
    expect(html).not.toMatch(/users\/\d+/);
    expect(html).not.toMatch(/[\w.+-]+@[\w-]+\.[\w.]+/);
    // And no credential or connection state belonging to somebody else.
    expect(html).not.toMatch(/oauth|access[_ ]token|refresh[_ ]token|scope[s]?=/i);
  });

  it("keeps attribution categorical rather than numeric", async () => {
    // md/05 §A.2.1: certainty and attribution are categories. A percentage is
    // a confidence claim the pipeline cannot support and a reader cannot check.
    render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 1, unresolvedActors: 1 }))),
      }),
    );
    await screen.findAllByText(/shipped rate limiting/i);

    const main = await screen.findByRole("main");
    expect(main.textContent).not.toMatch(/\d+\s?%|\bconfidence\b|\b0\.\d+\b/i);
  });

  it("passes an axe audit with both attribution states on screen", async () => {
    const { container } = render(
      client({
        myWeek: vi.fn(() => Promise.resolve(weekWith({ resolvedActors: 1, unresolvedActors: 1 }))),
      }),
    );
    await screen.findByText(/has not connected their account/i);

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("correcting", () => {
  it("is one action for the three kinds that need no wording", async () => {
    const correctFact = vi.fn(() => Promise.resolve({ correctedFactId: "x" }));
    render(client({ correctFact }));

    await screen.findAllByText(/shipped rate limiting/i);
    await userEvent.click(screen.getByRole("button", { name: /not right/i }));
    await userEvent.click(screen.getByRole("button", { name: /that was not me/i }));

    expect(correctFact).toHaveBeenCalledWith(
      SESSION.workspaces[0]?.workspace.id,
      "11111111-1111-1111-1111-111111111111",
      { kind: "wrong_person" },
    );
  });

  it("asks for wording only where wording is the correction", async () => {
    const correctFact = vi.fn(() => Promise.resolve({ correctedFactId: "x" }));
    render(client({ correctFact }));

    await screen.findAllByText(/shipped rate limiting/i);
    await userEvent.click(screen.getByRole("button", { name: /not right/i }));

    const field = screen.getByLabelText(/what it should have said/i);
    // Pre-filled with what CAIRN said, so a small fix is a small edit rather
    // than retyping a sentence somebody did not write in the first place.
    expect(field).toHaveValue("Priya shipped rate limiting to production.");

    await userEvent.clear(field);
    await userEvent.type(field, "Priya reviewed the rate limiting change.");
    await userEvent.click(screen.getByRole("button", { name: /save correction/i }));

    expect(correctFact).toHaveBeenCalledWith(
      SESSION.workspaces[0]?.workspace.id,
      "11111111-1111-1111-1111-111111111111",
      { kind: "reworded", statement: "Priya reviewed the rate limiting change." },
    );
  });

  it("confirms in words rather than letting the row vanish", async () => {
    // A row that simply disappears leaves the reader unsure whether their
    // correction was recorded or the page moved.
    render(client({ correctFact: vi.fn(() => Promise.resolve({ correctedFactId: "x" })) }));

    await screen.findAllByText(/shipped rate limiting/i);
    await userEvent.click(screen.getByRole("button", { name: /not right/i }));
    await userEvent.click(screen.getByRole("button", { name: /did not happen/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/recorded/i);
  });

  it("says so when a correction cannot be recorded, and keeps the controls usable", async () => {
    render(client({ correctFact: vi.fn(() => Promise.reject(apiError(503))) }));

    await screen.findAllByText(/shipped rate limiting/i);
    await userEvent.click(screen.getByRole("button", { name: /not right/i }));
    await userEvent.click(screen.getByRole("button", { name: /no longer true/i }));

    expect(await screen.findByRole("alert")).toBeVisible();
    // Still correctable. A failed attempt that disables the control turns a
    // transient outage into a record the person can never fix.
    expect(screen.getByRole("button", { name: /no longer true/i })).toBeEnabled();
  });

  it("names each correction control by the claim it corrects", async () => {
    // A screen-reader user navigating by control list would otherwise hear a
    // page of identical "Not right?" buttons with nothing to tell them apart.
    render();
    await screen.findAllByText(/shipped rate limiting/i);

    expect(
      screen.getByRole("button", { name: /not right\?.*shipped rate limiting/i }),
    ).toBeInTheDocument();
  });

  it("passes an axe audit with the correction controls open", async () => {
    const { container } = render();
    await screen.findAllByText(/shipped rate limiting/i);
    await userEvent.click(screen.getByRole("button", { name: /not right/i }));

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("the shell", () => {
  it("offers this screen in the navigation, under the name the screen uses", async () => {
    render();

    const nav = await screen.findByRole("navigation", { name: /primary/i });
    expect(within(nav).getByRole("link", { name: /your record/i })).toHaveAttribute("href", "/me");
  });
});
