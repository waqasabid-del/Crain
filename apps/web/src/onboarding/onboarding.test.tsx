import type { Onboarding } from "@cairn/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, router, SESSION } from "../test/harness.js";
import { OnboardingPage } from "./OnboardingPage.js";
import { SignupPage, slugify } from "./SignupPage.js";

/**
 * Step 20's exit criterion, and it is not "the flow works".
 *
 * *Under ten minutes from signup to first real output*, and **never an empty
 * state**. The second is the one worth testing hard, because it is the one a
 * naive implementation gets wrong on the screen where abandonment costs most: a
 * workspace connected ninety seconds ago genuinely has no brief, and a product
 * that says "nothing here yet" reads as broken rather than as busy.
 *
 * So most of what follows asserts that at every stage — not connected, importing
 * with zero commits, importing with some, finished with nothing found — the
 * reader is told something true and specific.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom: the rule samples rendered pixels from a canvas. See
  // `a11y.test.tsx` for the full reasoning, and `packages/ui` for where
  // contrast is actually measured.
  rules: { "color-contrast": { enabled: false } },
} as const;

function onboarding(overrides: Partial<Onboarding> = {}): Onboarding {
  return {
    stage: "importing",
    connected: true,
    accountLogin: "acme-inc",
    repositories: [],
    commitsImported: 0,
    factsAvailable: 0,
    importing: true,
    ...overrides,
  };
}

/**
 * A client plus the spy, held separately.
 *
 * Reading `client.getOnboarding` back out to assert on it destructures a
 * method off an interface, which `unbound-method` flags — and the spy is what
 * the assertion is about, so holding it directly is also clearer.
 */
function clientWith(state: Onboarding): {
  client: ReturnType<typeof createStubClient>;
  getOnboarding: ReturnType<typeof vi.fn<() => Promise<Onboarding>>>;
} {
  const getOnboarding = vi.fn(() => Promise.resolve(state));
  const client = createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    getOnboarding,
  });
  return { client, getOnboarding };
}

function renderOnboarding(state: Onboarding): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <OnboardingPage />
    </AppLayout>,
    { client: clientWith(state).client, route: "/onboarding" },
  );
}

describe("never an empty state", () => {
  it("offers the one action that matters when nothing is connected", async () => {
    renderOnboarding(onboarding({ stage: "not_connected", connected: false, importing: false }));

    expect(await screen.findByRole("heading", { name: /connect your code/i })).toBeVisible();
    // A real link, so middle-click and open-in-new-tab work — a cautious admin
    // about to grant access to their organisation wants to check where it goes.
    expect(screen.getByRole("link", { name: /connect github/i })).toHaveAttribute("href");
  });

  it("says what is happening in the first seconds, before any commit has arrived", async () => {
    // The hardest moment: connected, zero of everything. A spinner here is what
    // makes a product feel broken.
    renderOnboarding(onboarding({ commitsImported: 0, factsAvailable: 0 }));

    expect(await screen.findByRole("heading", { name: /reading acme-inc/i })).toBeVisible();
    expect(screen.getByText(/commits read/i)).toBeVisible();
    expect(screen.getByText(/keeps going/i)).toBeVisible();
  });

  it("shows real counters rather than an invented percentage", async () => {
    // GitHub does not say how many commits a repository holds before it is
    // walked, so a percentage would be fabricated — and a fabricated one always
    // stalls near the end, which reads as broken rather than as unknown.
    renderOnboarding(
      onboarding({
        commitsImported: 1284,
        factsAvailable: 0,
        repositories: [
          { repository: "acme-inc/api", state: "running", commitsImported: 900, finished: false },
          { repository: "acme-inc/web", state: "completed", commitsImported: 384, finished: true },
        ],
      }),
    );

    // Wait for the counters themselves, not merely for the shell. `main`
    // appears as soon as the session resolves, which is before the onboarding
    // request has answered — asserting on its text at that moment reads the
    // loading state and fails for a reason unrelated to the assertion.
    await screen.findByText(/commits read/i);
    const main = await screen.findByRole("main");
    // Matched against the rendered text rather than by exact string: the count
    // goes through `toLocaleString`, and asserting "1,284" would make the test
    // depend on the machine's locale — a separator that differs in CI is a
    // failure with nothing to do with the code.
    expect(main.textContent).toMatch(/1\D?284/);
    expect(main.textContent).toMatch(/1 of 2/);
    expect(main.textContent).not.toMatch(/\d+\s*%/);
  });

  it("offers the brief the moment there is anything to read, without waiting for the import", async () => {
    // This is what makes "under ten minutes to first output" achievable for a
    // team with five years of history: first output is not a finished import.
    renderOnboarding(onboarding({ stage: "understanding", factsAvailable: 42, importing: true }));

    expect(await screen.findByRole("link", { name: /open your brief/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("says the repositories were quiet rather than spinning forever", async () => {
    // Import finished, nothing found. Not a failure and not a loading state —
    // a spinner that never resolves is the worst of the three.
    renderOnboarding(
      onboarding({ stage: "ready", importing: false, factsAvailable: 0, commitsImported: 0 }),
    );

    expect(await screen.findByRole("heading", { name: /nothing to summarise yet/i })).toBeVisible();
    expect(screen.getByText(/real answer rather than a problem/i)).toBeVisible();
  });

  it("explains a failure and offers a retry", async () => {
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(SESSION)),
      getOnboarding: vi.fn(() => Promise.reject(apiError(503))),
    });

    renderRoute(
      <AppLayout>
        <OnboardingPage />
      </AppLayout>,
      { client, route: "/onboarding" },
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toBeVisible();
    expect(within(alert).getByRole("button", { name: /try again|retry/i })).toBeVisible();
  });

  it("passes an axe audit while importing", async () => {
    const { container } = renderOnboarding(onboarding({ commitsImported: 12 }));
    await screen.findByRole("heading", { name: /reading acme-inc/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("polling", () => {
  it("stops once the import is finished", async () => {
    // A tab left open overnight must not be a polling loop. The interval keeps
    // ticking; the guard inside it is what stops the requests.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { client, getOnboarding } = clientWith(
        onboarding({ stage: "ready", importing: false }),
      );

      renderRoute(
        <AppLayout>
          <OnboardingPage />
        </AppLayout>,
        { client, route: "/onboarding" },
      );

      await waitFor(() => {
        expect(getOnboarding).toHaveBeenCalledTimes(1);
      });

      await vi.advanceTimersByTimeAsync(30_000);
      expect(getOnboarding).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps asking while the import is running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { client, getOnboarding } = clientWith(onboarding({ importing: true }));

      renderRoute(
        <AppLayout>
          <OnboardingPage />
        </AppLayout>,
        { client, route: "/onboarding" },
      );

      await waitFor(() => {
        expect(getOnboarding).toHaveBeenCalledTimes(1);
      });

      await vi.advanceTimersByTimeAsync(10_000);
      expect(getOnboarding.mock.calls.length).toBeGreaterThan(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("signup", () => {
  it("creates the workspace and goes straight to connecting a source", async () => {
    // No congratulations screen between the account and the only action that
    // matters. The clock md/11 §3 counts is already running.
    // Typed on the client's own signature, so the assertion below reads the
    // real body rather than a cast — a cast here would let the test keep
    // passing if the field names changed.
    const signUp: ReturnType<typeof createStubClient>["signUp"] = vi.fn(() =>
      Promise.resolve(SESSION),
    );
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      signUp,
    });

    renderRoute(<SignupPage />, { client, route: "/signup" });

    await userEvent.type(screen.getByLabelText(/your name/i), "Ali Rahman");
    await userEvent.type(screen.getByLabelText(/work email/i), "ali@acme.test");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await userEvent.type(screen.getByLabelText(/company or team/i), "Acme Inc");
    await userEvent.click(screen.getByRole("button", { name: /create workspace/i }));

    await waitFor(() => {
      expect(router.replace).toHaveBeenCalledWith("/onboarding");
    });

    const body = vi.mocked(signUp).mock.calls[0]?.[0];
    expect(body?.workspaceName).toBe("Acme Inc");
    // Derived, not asked for. A reader inventing a URL-safe identifier in their
    // first thirty seconds is a reader deciding whether this is worth it.
    expect(body?.workspaceSlug).toMatch(/^acme-inc-[a-z0-9]{6}$/);
  });

  it("states the password rule before it can be broken", () => {
    const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(null)) });
    renderRoute(<SignupPage />, { client, route: "/signup" });

    expect(screen.getByText(/at least 12 characters/i)).toBeVisible();
  });

  it("explains a rejected signup without losing what was typed", async () => {
    // Clearing the form on failure is the fastest way to lose someone who has
    // just spent thirty seconds on it.
    const client = createStubClient({
      getSession: vi.fn(() => Promise.resolve(null)),
      signUp: vi.fn(() => Promise.reject(apiError(409))),
    });

    renderRoute(<SignupPage />, { client, route: "/signup" });

    await userEvent.type(screen.getByLabelText(/work email/i), "taken@acme.test");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await userEvent.type(screen.getByLabelText(/company or team/i), "Acme Inc");
    await userEvent.click(screen.getByRole("button", { name: /create workspace/i }));

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByLabelText(/work email/i)).toHaveValue("taken@acme.test");
    expect(screen.getByRole("button", { name: /create workspace/i })).toBeEnabled();
  });

  it("passes an axe audit", async () => {
    const client = createStubClient({ getSession: vi.fn(() => Promise.resolve(null)) });
    const { container } = renderRoute(<SignupPage />, { client, route: "/signup" });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });
});

describe("slugify", () => {
  it("produces a URL-safe identifier with a collision-resistant suffix", () => {
    // Two companies called Acme is not an edge case. Colliding on the readable
    // part is fine; colliding on the whole slug is a failed signup.
    expect(slugify("Acme Inc")).toMatch(/^acme-inc-[a-z0-9]{6}$/);
    expect(slugify("Acme Inc")).not.toBe(slugify("Acme Inc"));
  });

  it("survives a name with nothing usable in it", () => {
    // A workspace called "?!" must still produce a valid slug rather than an
    // empty one the API rejects with a message about a field nobody filled in.
    expect(slugify("?!")).toMatch(/^workspace-[a-z0-9]{6}$/);
  });

  it("strips accents rather than dropping the word", () => {
    expect(slugify("Zürich Ausbau")).toMatch(/^zurich-ausbau-[a-z0-9]{6}$/);
  });
});
