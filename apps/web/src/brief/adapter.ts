import type { CairnClient, Facets, FactQuery, SearchQuery, SearchResults } from "@cairn/api-client";

import { CONTENT_SOURCE } from "../env.js";
import { SAMPLE_BRIEF, SAMPLE_FACTS } from "./sample.js";
import type { Brief, Fact } from "./types.js";

/** Where the Brief and Feed screens get their content: the API, or a fixed
 * example. `api` is the default — a product promising "every claim links to its
 * source" must not quietly invent claims — and `sample` says so in a banner. */
export interface ContentSource {
  getBrief(workspaceId: string, signal?: AbortSignal): Promise<Brief>;
  getFacts(workspaceId: string, query?: FactQuery, signal?: AbortSignal): Promise<FactList>;
  getFacets(workspaceId: string, signal?: AbortSignal): Promise<Facets>;
  search(workspaceId: string, query: SearchQuery, signal?: AbortSignal): Promise<SearchResults>;
}

export interface FactList {
  items: Fact[];
  nextCursor?: string;
}

/** The API, through the generated client. Takes the client rather than the
 * singleton so a test can substitute one. */
export function apiSource(client: CairnClient): ContentSource {
  return {
    getBrief: async (workspaceId, signal) => {
      return await client.getBrief(workspaceId, undefined, signal ? { signal } : undefined);
    },

    getFacts: async (workspaceId, query, signal) => {
      const page = await client.listFacts(workspaceId, query, signal ? { signal } : undefined);
      const items = page.items ?? [];
      // Spread, not `?? undefined`: `exactOptionalPropertyTypes` is on.
      return page.nextCursor ? { items, nextCursor: page.nextCursor } : { items };
    },

    getFacets: async (workspaceId, signal) => {
      return await client.getFacets(workspaceId, signal ? { signal } : undefined);
    },

    search: async (workspaceId, query, signal) => {
      return await client.search(workspaceId, query, signal ? { signal } : undefined);
    },
  };
}

/** The example content, filtered and searched in the browser, by the server's
 * own rules: filters intersect, a facet lists only values something matches.
 * Search is substring matching, so hits are `words` and `semantic` is false —
 * there are no embeddings here and the screen must not claim otherwise. */
const sampleSource: ContentSource = {
  getBrief: () => Promise.resolve(SAMPLE_BRIEF),

  getFacts: (_workspaceId, query) =>
    Promise.resolve({ items: SAMPLE_FACTS.filter((fact) => matches(fact, query)) }),

  getFacets: () =>
    Promise.resolve({
      // No resolved identities here, so the mention is both id and name.
      people: unique(
        SAMPLE_FACTS.flatMap((fact) => (fact.people ?? []).map((person) => person.mention)),
      ).map((mention) => ({ id: mention, name: mention })),
      projects: unique(
        SAMPLE_FACTS.flatMap((fact) => (fact.sources ?? []).map((source) => source.project)),
      ),
      sources: unique(
        SAMPLE_FACTS.flatMap((fact) => (fact.sources ?? []).map((source) => source.source)),
      ),
    }),

  search: (_workspaceId, query) =>
    Promise.resolve({
      items: SAMPLE_FACTS.filter(
        (fact) =>
          matches(fact, query) && fact.statement.toLowerCase().includes(query.q.toLowerCase()),
      ).map((fact) => ({ fact, matchedOn: "words" as const })),
      truncated: false,
      semantic: false,
    }),
};

function unique(values: (string | undefined | null)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

/** The sample equivalent of `feed.conditions` — the same rules, in one browser. */
function matches(fact: Fact, query: FactQuery | undefined): boolean {
  if (query === undefined) return true;
  const sources = fact.sources ?? [];

  if (query.source?.length && !sources.some((item) => query.source?.includes(item.source))) {
    return false;
  }
  if (
    query.project?.length &&
    !sources.some(({ project }) => typeof project === "string" && query.project?.includes(project))
  ) {
    return false;
  }
  if (query.kind?.length && !query.kind.includes(fact.kind)) return false;
  if (
    query.person?.length &&
    !(fact.people ?? []).some((person) => query.person?.includes(person.mention))
  ) {
    return false;
  }

  // An undated fact survives a date filter, as server-side: unknown, not outside.
  const occurred = fact.occurredAt;
  if (occurred !== undefined && occurred !== null) {
    if (query.since !== undefined && occurred < query.since) return false;
    if (query.until !== undefined && occurred > query.until) return false;
  }
  return true;
}

/** A function of the client, not a module constant: a singleton would put the
 * real API back into every test that renders a screen. */
export function contentSourceFor(client: CairnClient): ContentSource {
  return CONTENT_SOURCE === "sample" ? sampleSource : apiSource(client);
}

/** Whether the reader is looking at example content, so the screen can say so. */
export const IS_SAMPLE_CONTENT = CONTENT_SOURCE === "sample";
