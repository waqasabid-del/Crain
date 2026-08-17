import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { createStubClient, MEMBERS, renderRoute, SESSION } from "../test/harness.js";
import { PeoplePage } from "./PeoplePage.js";

/**
 * The team list, and the one line it is allowed to say about identity.
 *
 * A members list is where comparative measurement between people first appears
 * in almost every product of this kind: an activity column, a "last seen", a
 * count of anything. md/05 §B.3.3 makes that a change of product rather than a
 * change of style, so the tests here are almost entirely about absence.
 *
 * Attribution transparency pulls at exactly this boundary, because the obvious
 * place to show "who has not connected an account" is next to the list of
 * people. That would be a connection leaderboard with a polite name. What this
 * screen says instead is addressed to the reader about their own record, and
 * these tests hold it there.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    listMembers: vi.fn(() => Promise.resolve(MEMBERS)),
    ...overrides,
  });
}

function renderPeople(stub = client()): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <PeoplePage />
    </AppLayout>,
    { client: stub, route: "/people" },
  );
}

describe("the team list", () => {
  it("lists who is here and what each of them can configure", async () => {
    renderPeople();

    expect(await screen.findByRole("rowheader", { name: /ali rahman/i })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: /^role$/i })).toBeVisible();
  });

  it("carries no ranking, score or per-person count of anything", async () => {
    // The assertion the whole screen exists to keep passing. It is written as a
    // vocabulary check rather than a structural one because the failure arrives
    // as a friendly-looking column, not as a refactor.
    renderPeople();
    await screen.findByRole("rowheader", { name: /ali rahman/i });

    const main = await screen.findByRole("main");
    const text = main.textContent;

    expect(text).not.toMatch(/\b(?:most|top|least|rank\w*|score\w*|leaderboard)\b/i);
    expect(text).not.toMatch(/\bcommits?\b/i);
    expect(text).not.toMatch(/\bcontributions?\b/i);
    expect(text).not.toMatch(/\b(?:activity|facts|items)\s+count\b/i);
    expect(text).not.toMatch(/\blast\s+(?:seen|active)\b/i);
  });

  it("says nothing about any colleague's connected accounts", async () => {
    // The tempting feature, and the one that turns this page into a list of
    // people to chase. Whether somebody has connected an account is theirs.
    renderPeople();
    await screen.findByRole("rowheader", { name: /ali rahman/i });

    const table = screen.getByRole("table");
    expect(table.textContent).not.toMatch(/connected|unresolved|identit/i);
  });

  it("addresses the reader about their own record instead", async () => {
    // What is genuinely worth saying here: why your own name is sometimes
    // missing from a fact elsewhere, and where you fix that.
    renderPeople();

    expect(
      await screen.findByText(/if work of yours is recorded elsewhere without your name/i),
    ).toBeVisible();

    // Scoped to `main`: the sidebar names the same destination, which is the
    // point — the note sends people somewhere they can already get to.
    const main = await screen.findByRole("main");
    expect(within(main).getByRole("link", { name: /^preferences$/i })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("does not read as a defect notice", async () => {
    renderPeople();

    const note = await screen.findByText(
      /if work of yours is recorded elsewhere without your name/i,
    );
    const text = note.textContent;
    expect(text).not.toMatch(/error|failed|failure|problem|invalid|unable|broken|denied/i);
  });

  it("says so when the team cannot be loaded, with a way to try again", async () => {
    renderPeople(client({ listMembers: vi.fn(() => Promise.reject(new Error("offline"))) }));

    expect(await screen.findByRole("heading", { name: /could not be loaded/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /try again/i })).toBeVisible();
  });

  it("explains an empty workspace rather than showing an empty table", async () => {
    renderPeople(client({ listMembers: vi.fn(() => Promise.resolve([])) }));

    expect(await screen.findByRole("heading", { name: /nobody here yet/i })).toBeVisible();
  });

  it("passes an axe audit with the notes on screen", async () => {
    const { container } = renderPeople();
    await screen.findByRole("rowheader", { name: /ali rahman/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});
