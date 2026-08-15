import type { Facets, FactPage, FactQuery, SearchQuery, SearchResults } from "@cairn/api-client";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, type Mock } from "vitest";
import { axe } from "vitest-axe";

import AppLayout from "../app/(app)/layout.js";
import { apiError, createStubClient, renderRoute, router, SESSION } from "../test/harness.js";
import { FeedPage } from "./FeedPage.js";

/**
 * Step 24's exit criterion: **filter by person, project, source and date; search
 * returns grounded results.**
 *
 * The filtering half is mostly mechanical, and the tests assert the thing that
 * actually breaks: that what the reader chose reaches the request. A filter that
 * renders and does not narrow is indistinguishable from one that works, on a
 * screen where the reader cannot see what they were not shown.
 *
 * The search half needs its definition stated, because "grounded" is where this
 * kind of product usually starts overclaiming. It means the reader is looking at
 * stored facts with their evidence attached — never at prose composed from them.
 * So there is a test asserting the *absence* of a summary, which is unusual and
 * is the point: the failure mode is a helpful-looking paragraph nobody can check.
 */

const AXE_OPTIONS = {
  // Cannot run in jsdom — see `a11y.test.tsx`.
  rules: { "color-contrast": { enabled: false } },
} as const;

const FACETS: Facets = {
  people: [
    { id: "aaaaaaaa-0000-0000-0000-000000000001", name: "Priya Nair" },
    { id: "aaaaaaaa-0000-0000-0000-000000000002", name: "Ali Rahman" },
  ],
  projects: ["acme/gateway", "acme/payments"],
  sources: ["github", "chat"],
};

const SHIPPED = {
  id: "11111111-1111-1111-1111-111111111111",
  kind: "delivery",
  statement: "Priya shipped rate limiting to production.",
  certainty: "observed" as const,
  origin: "extracted" as const,
  validFrom: "2026-08-10T09:00:00Z",
  occurredAt: "2026-08-10T09:00:00Z",
  people: [{ mention: "Priya Nair" }],
  sources: [
    {
      evidenceId: "pr-482",
      source: "github",
      project: "acme/payments",
      url: "https://github.com/acme/payments/pull/482",
    },
  ],
};

const BLOCKED = {
  ...SHIPPED,
  id: "22222222-2222-2222-2222-222222222222",
  kind: "blocker",
  statement: "Ali is blocked on the staging certificate.",
  people: [{ mention: "Ali Rahman" }],
  sources: [{ evidenceId: "msg-9", source: "chat" }],
};

const PAGE: FactPage = { items: [SHIPPED, BLOCKED] };

function client(overrides = {}): ReturnType<typeof createStubClient> {
  return createStubClient({
    getSession: vi.fn(() => Promise.resolve(SESSION)),
    getFacets: vi.fn(() => Promise.resolve(FACETS)),
    listFacts: vi.fn(() => Promise.resolve(PAGE)),
    ...overrides,
  });
}

function renderFeed(stub = client(), search = ""): ReturnType<typeof renderRoute> {
  return renderRoute(
    <AppLayout>
      <FeedPage />
    </AppLayout>,
    { client: stub, route: "/feed", search },
  );
}

/**
 * A spy standing in for one client method.
 *
 * Held directly rather than read back off the stub, so the query the screen sent
 * is typed as `FactQuery` instead of `any` — which is what makes an assertion
 * about `person` fail to compile when the field is renamed, rather than pass
 * against `undefined`.
 */
type FactsSpy = Mock<(workspaceId: string, query?: FactQuery) => Promise<FactPage>>;
type SearchSpy = Mock<(workspaceId: string, query: SearchQuery) => Promise<SearchResults>>;

function factsSpy(page: FactPage = PAGE): FactsSpy {
  return vi.fn((_workspaceId: string, _query?: FactQuery) => Promise.resolve(page));
}

/** The query the screen sent on its most recent call. */
function lastQuery(spy: FactsSpy): FactQuery {
  return spy.mock.calls.at(-1)?.[1] ?? {};
}

describe("the stream", () => {
  it("groups what happened by the kind of thing it is", async () => {
    renderFeed();

    // Blockers first: they are the thing a reader can act on, and a blocker
    // nobody reports is the highest-cost missed signal in the product.
    const blocked = await screen.findByRole("heading", { name: /blocked/i });
    const delivered = await screen.findByRole("heading", { name: /delivered/i });
    expect(
      blocked.compareDocumentPosition(delivered) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("says nothing has been recorded differently from nothing matching", async () => {
    // Telling somebody with an empty workspace to try clearing filters they
    // never set sends them looking for a fault in a control they did not touch.
    renderFeed(client({ listFacts: vi.fn(() => Promise.resolve({ items: [] })) }));

    expect(await screen.findByRole("heading", { name: /nothing recorded yet/i })).toBeVisible();
  });

  it("explains an empty result as a consequence of the filters when there are filters", async () => {
    renderFeed(client({ listFacts: vi.fn(() => Promise.resolve({ items: [] })) }), "source=chat");

    expect(
      await screen.findByRole("heading", { name: /nothing matches these filters/i }),
    ).toBeVisible();
  });

  it("offers more only when there is more, and appends rather than replaces", async () => {
    const listFacts = vi
      .fn()
      .mockResolvedValueOnce({ items: [SHIPPED], nextCursor: "abc" })
      .mockResolvedValueOnce({ items: [BLOCKED] });
    renderFeed(client({ listFacts }));

    await screen.findAllByText(/shipped rate limiting/i);
    await userEvent.click(await screen.findByRole("button", { name: /show more/i }));

    // Both on screen: a "show more" that replaced the page would look like a
    // filter nobody applied.
    expect(await screen.findAllByText(/blocked on the staging certificate/i)).not.toHaveLength(0);
    expect(screen.getAllByText(/shipped rate limiting/i)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: /show more/i })).not.toBeInTheDocument();
  });

  it("keeps the citation disclosure the Brief has", async () => {
    // The Feed maps facts onto the same claim component for exactly this
    // reason: a second card component is where one screen quietly loses its
    // provenance affordance.
    renderFeed();

    const sources = await screen.findAllByText(/1 source/i);
    expect(sources.length).toBeGreaterThan(0);
  });
});

describe("filtering", () => {
  it("offers only the values this workspace actually has", async () => {
    renderFeed();

    const projects = await screen.findByLabelText(/^project$/i);
    expect(
      within(projects)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["All projects", "acme/gateway", "acme/payments"]);
  });

  it("does not render a filter with nothing to put in it", async () => {
    // A "Projects" menu holding only "All projects" teaches a reader the product
    // is broken before they have read a single fact.
    renderFeed(
      client({
        getFacets: vi.fn(() => Promise.resolve({ people: [], projects: [], sources: ["github"] })),
      }),
    );

    await screen.findByLabelText(/^source$/i);
    expect(screen.queryByLabelText(/^project$/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^person$/i)).not.toBeInTheDocument();
  });

  it("sends the person the reader chose", async () => {
    const listFacts = factsSpy();
    renderFeed(client({ listFacts }));

    await userEvent.selectOptions(await screen.findByLabelText(/^person$/i), "Priya Nair");
    await userEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    expect(lastQuery(listFacts).person).toEqual([FACETS.people?.[0]?.id]);
  });

  it("sends the project and the source", async () => {
    const listFacts = factsSpy();
    renderFeed(client({ listFacts }));

    await userEvent.selectOptions(await screen.findByLabelText(/^project$/i), "acme/gateway");
    await userEvent.selectOptions(screen.getByLabelText(/^source$/i), "GitHub");
    await userEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    const query = lastQuery(listFacts);
    expect(query.project).toEqual(["acme/gateway"]);
    expect(query.source).toEqual(["github"]);
  });

  it("treats a single day as that whole day, in the reader's own timezone", async () => {
    // Two properties in one test, and both were wrong before it existed.
    //
    // A reader who types the same date in both boxes means "that day": sending
    // midnight to midnight returns nothing, and everyone concludes the filter is
    // broken rather than precise.
    //
    // And the day is theirs, not UTC's. Pinning the instants to UTC asks
    // somebody in UTC+13 for a window that starts mid-morning — their own
    // activity from that morning missing, the previous evening's included, with
    // nothing on screen to explain either. Asserted against locally-constructed
    // instants so the test states the intent rather than one zone's answer.
    const listFacts = factsSpy();
    renderFeed(client({ listFacts }));

    await userEvent.type(await screen.findByLabelText(/^from$/i), "2026-08-10");
    await userEvent.type(screen.getByLabelText(/^to$/i), "2026-08-10");
    await userEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    const query = lastQuery(listFacts);
    expect(query.since).toBe(new Date(2026, 7, 10, 0, 0, 0, 0).toISOString());
    expect(query.until).toBe(new Date(2026, 7, 10, 23, 59, 59, 999).toISOString());
  });

  it("starts from the filters in the URL", async () => {
    // What makes a filtered feed something a person can send to somebody else.
    const listFacts = factsSpy();
    renderFeed(client({ listFacts }), "source=chat&project=acme%2Fgateway");

    await screen.findByLabelText(/^source$/i);

    const query = lastQuery(listFacts);
    expect(query.source).toEqual(["chat"]);
    expect(query.project).toEqual(["acme/gateway"]);
  });

  it("records the filters in the URL as they are applied", async () => {
    renderFeed();

    await userEvent.selectOptions(await screen.findByLabelText(/^source$/i), "Chat");
    await userEvent.click(screen.getByRole("button", { name: /^apply$/i }));

    expect(router.replace).toHaveBeenCalledWith("/feed?source=chat");
  });

  it("clears back to everything", async () => {
    const listFacts = factsSpy();
    renderFeed(client({ listFacts }), "source=chat");

    await userEvent.click(await screen.findByRole("button", { name: /clear/i }));

    expect(lastQuery(listFacts)).toEqual({});
    expect(router.replace).toHaveBeenLastCalledWith("/feed");
  });
});

describe("search", () => {
  const RESULTS: SearchResults = {
    items: [{ fact: SHIPPED, matchedOn: "words" }],
    truncated: false,
    semantic: true,
  };

  function searchSpy(results: SearchResults = RESULTS): SearchSpy {
    return vi.fn((_workspaceId: string, _query: SearchQuery) => Promise.resolve(results));
  }

  function searching(overrides = {}): ReturnType<typeof createStubClient> {
    return client({ search: searchSpy(), ...overrides });
  }

  it("returns stored facts with their evidence", async () => {
    renderFeed(searching(), "q=rate+limiting");

    expect(await screen.findAllByText(/shipped rate limiting/i)).not.toHaveLength(0);
    // The promise the endpoint is making: a result a reader can go and check.
    expect(await screen.findByRole("link", { name: /pr-482/i })).toHaveAttribute(
      "href",
      "https://github.com/acme/payments/pull/482",
    );
  });

  it("composes no answer above the results", async () => {
    // The failure this is guarding against is not a wrong result — it is a
    // fluent paragraph summarising the results, which is what gets believed
    // while the citations underneath go unopened.
    renderFeed(searching(), "q=rate+limiting");

    const results = await screen.findByRole("list", { name: /matched your words/i });
    const main = await screen.findByRole("main");

    expect(main.textContent).not.toMatch(/in summary|overall|it (looks|seems) like/i);

    // One row per result and no others. A summary sentence, a "CAIRN thinks"
    // line or a synthesised lead would all show up here as an extra item — and
    // every row that is here carries the fact's own words, verbatim.
    //
    // Direct children rather than `getAllByRole("listitem")`: each result nests
    // its own list of citations, which is provenance rather than an extra
    // result.
    const rows = [...results.children];
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent(SHIPPED.statement);
  });

  it("separates what matched the words from what matched the meaning", async () => {
    // The two fail differently. A semantic near-miss shown in the same list and
    // the same style as an exact hit gets believed more than it has earned.
    renderFeed(
      searching({
        search: vi.fn(() =>
          Promise.resolve({
            items: [
              { fact: SHIPPED, matchedOn: "words" },
              { fact: BLOCKED, matchedOn: "meaning" },
            ],
            truncated: false,
            semantic: true,
          }),
        ),
      }),
      "q=rate+limiting",
    );

    expect(await screen.findByRole("heading", { name: /matched your words/i })).toBeVisible();
    expect(screen.getByRole("heading", { name: /found by meaning/i })).toBeVisible();
    expect(screen.getByText(/do not contain what you typed/i)).toBeVisible();
  });

  it("does not invent a section for a kind of match that returned nothing", async () => {
    renderFeed(searching(), "q=rate+limiting");

    await screen.findByRole("heading", { name: /matched your words/i });
    expect(screen.queryByRole("heading", { name: /found by meaning/i })).not.toBeInTheDocument();
  });

  it("says when it is showing the strongest matches rather than all of them", async () => {
    // A search that quietly returned its first twenty-five of two hundred looks
    // exactly like one that found twenty-five.
    renderFeed(
      searching({
        search: vi.fn(() => Promise.resolve({ ...RESULTS, truncated: true })),
      }),
      "q=rate+limiting",
    );

    expect(await screen.findByText(/strongest matches, not all of them/i)).toBeVisible();
  });

  it("explains an empty result in terms of what CAIRN can know", async () => {
    renderFeed(
      searching({
        search: vi.fn(() => Promise.resolve({ items: [], truncated: false, semantic: true })),
      }),
      "q=quarterly+revenue",
    );

    expect(await screen.findByRole("heading", { name: /quarterly revenue/i })).toBeVisible();
    expect(screen.getByText(/only searches what it has recorded/i)).toBeVisible();
  });

  it("narrows the search by the same filters as the feed", async () => {
    // Narrowing the screen and then typing must not widen it again.
    const search = searchSpy();
    renderFeed(client({ search }), "q=rate&source=chat");

    await screen.findAllByText(/shipped rate limiting/i);
    const query = search.mock.calls.at(-1)?.[1];
    expect(query?.q).toBe("rate");
    expect(query?.source).toEqual(["chat"]);
  });

  it("says so when the search could not be run", async () => {
    renderFeed(searching({ search: vi.fn(() => Promise.reject(apiError(503))) }), "q=rate");

    expect(await screen.findByRole("heading", { name: /could not be run/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /try again/i })).toBeVisible();
  });

  it("does not run a search for an empty box", async () => {
    // `?q=` returning the whole workspace under a "results" heading would look
    // like search working.
    const search = searchSpy();
    const listFacts = factsSpy();
    renderFeed(client({ search, listFacts }));

    await screen.findAllByText(/shipped rate limiting/i);
    expect(search).not.toHaveBeenCalled();
    expect(listFacts).toHaveBeenCalled();
  });
});

describe("accessibility", () => {
  it("passes an axe audit with the filters and the stream", async () => {
    const { container } = renderFeed();
    await screen.findByLabelText(/^project$/i);

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("passes an axe audit with results on screen", async () => {
    const { container } = renderFeed(
      client({
        search: vi.fn(() =>
          Promise.resolve({
            items: [
              { fact: SHIPPED, matchedOn: "words" },
              { fact: BLOCKED, matchedOn: "meaning" },
            ],
            truncated: true,
            semantic: true,
          }),
        ),
      }),
      "q=rate",
    );
    await screen.findByRole("heading", { name: /matched your words/i });

    await expect(axe(container, AXE_OPTIONS)).resolves.toHaveNoViolations();
  });

  it("is reachable as a search landmark", async () => {
    // How somebody using a screen reader finds this without walking the page.
    renderFeed();
    expect(await screen.findByRole("search", { name: /feed/i })).toBeInTheDocument();
  });
});
