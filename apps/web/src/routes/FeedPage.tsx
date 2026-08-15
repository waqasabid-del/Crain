"use client";

import type { Facets, FactQuery } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactNode,
  type SyntheticEvent,
} from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { contentSourceFor, IS_SAMPLE_CONTENT, type ContentSource } from "../brief/adapter.js";
import type { Claim, Fact, FactKind } from "../brief/types.js";
import { ClaimList } from "../components/ClaimList.js";
import { PageHeader } from "../components/PageHeader.js";
import { SampleBanner } from "../components/SampleBanner.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./FeedPage.module.css";

/** Blockers and open questions first: they are what a reader can act on, and
 * an unreported blocker is the highest-cost missed signal (md/10 §1). */
const SECTIONS: { kind: FactKind; title: string }[] = [
  { kind: "blocker", title: "Blocked" },
  { kind: "open_question", title: "Open questions" },
  { kind: "decision", title: "Decisions" },
  { kind: "delivery", title: "Delivered" },
  { kind: "in_progress", title: "In progress" },
];

/** Plain-English names for the ingesting systems. No jargon by default (md/05 §A.1). */
const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  chat: "Chat",
  meeting: "Meetings",
  document: "Documents",
};

/** Mapped onto `Claim` rather than given a second card component, so the Feed
 * cannot quietly lose the sources disclosure the Brief has. */
function toClaim(fact: Fact): Claim {
  return {
    text: fact.statement,
    certainty: fact.certainty,
    citations: fact.sources ?? [],
    // The mention, not the resolved id: "who" is the reader's question, and
    // the resolution belongs to the identity graph.
    credits: (fact.people ?? []).map((person) => person.mention),
    hedgedBySystem: false,
  };
}

/** One person, project and source rather than several: a native multi-select
 * is hard to operate without a mouse. The API keeps the repeated-parameter
 * shape, so this is reversible in the interface alone. */
interface Narrowing {
  q: string;
  person: string;
  project: string;
  source: string;
  since: string;
  until: string;
}

const NOTHING: Narrowing = { q: "", person: "", project: "", source: "", since: "", until: "" };

function fromParams(params: URLSearchParams): Narrowing {
  return {
    q: params.get("q") ?? "",
    person: params.get("person") ?? "",
    project: params.get("project") ?? "",
    source: params.get("source") ?? "",
    since: params.get("since") ?? "",
    until: params.get("until") ?? "",
  };
}

function toParams(narrowing: Narrowing): URLSearchParams {
  const params = new URLSearchParams();
  // Keyed explicitly, not by `Object.entries`: a new `Narrowing` field must
  // not reach the URL without somebody deciding it should be shareable.
  const fields: (keyof Narrowing)[] = ["q", "person", "project", "source", "since", "until"];
  for (const field of fields) {
    if (narrowing[field] !== "") params.set(field, narrowing[field]);
  }
  return params;
}

function isNarrowed(narrowing: Narrowing): boolean {
  return Object.values(narrowing).some((value) => value !== "");
}

/** Both ends resolve against local time, not UTC: a UTC instant asks somebody
 * in UTC+13 for a window running mid-morning to mid-morning. `until` covers the
 * whole day, because the same date in both boxes means "that day". */
function asQuery(narrowing: Narrowing): FactQuery {
  const query: FactQuery = {};
  if (narrowing.person !== "") query.person = [narrowing.person];
  if (narrowing.project !== "") query.project = [narrowing.project];
  if (narrowing.source !== "") query.source = [narrowing.source];
  if (narrowing.since !== "") query.since = startOfLocalDay(narrowing.since);
  if (narrowing.until !== "") query.until = endOfLocalDay(narrowing.until);
  return query;
}

/** `2026-08-10` as the first instant of that day where the reader is. */
function startOfLocalDay(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year ?? 0, (month ?? 1) - 1, day ?? 1, 0, 0, 0, 0).toISOString();
}

/** The last instant of it. */
function endOfLocalDay(date: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(year ?? 0, (month ?? 1) - 1, day ?? 1, 23, 59, 59, 999).toISOString();
}

export function FeedPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Feed" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is no activity to show.
        </EmptyState>
      </>
    );
  }

  return <WorkspaceFeed workspaceId={activeWorkspace.id} />;
}

function WorkspaceFeed({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const content = useMemo(() => contentSourceFor(client), [client]);
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  /** The URL seeds this state and then records it; it does not drive it, or
   * every keystroke would be a navigation that can drop characters. */
  const [applied, setApplied] = useState<Narrowing>(() => fromParams(params));
  const [draft, setDraft] = useState<Narrowing>(applied);

  useEffect(() => {
    const next = toParams(applied).toString();
    router.replace(next === "" ? pathname : `${pathname}?${next}`);
  }, [applied, pathname, router]);

  const facets = useAsync(
    useCallback(
      (signal: AbortSignal): Promise<Facets> => content.getFacets(workspaceId, signal),
      [content, workspaceId],
    ),
    "load the filters",
  );

  function apply(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    setApplied(draft);
  }

  function clear(): void {
    setDraft(NOTHING);
    setApplied(NOTHING);
  }

  return (
    <>
      <PageHeader
        title="Feed"
        description="Everything CAIRN has recorded, with the evidence it rests on. The same information everyone on the team can see — including about leadership."
      />

      {IS_SAMPLE_CONTENT && <SampleBanner />}

      <FilterBar
        draft={draft}
        onChange={setDraft}
        onSubmit={apply}
        onClear={clear}
        showClear={isNarrowed(applied) || isNarrowed(draft)}
        facets={facets.state.status === "ready" ? facets.state.data : null}
      />

      {applied.q === "" ? (
        <Stream content={content} workspaceId={workspaceId} narrowing={applied} />
      ) : (
        <Results content={content} workspaceId={workspaceId} narrowing={applied} />
      )}
    </>
  );
}

function FilterBar({
  draft,
  facets,
  onChange,
  onSubmit,
  onClear,
  showClear,
}: {
  draft: Narrowing;
  facets: Facets | null;
  onChange: (next: Narrowing) => void;
  onSubmit: (event: SyntheticEvent<HTMLFormElement>) => void;
  onClear: () => void;
  showClear: boolean;
}): ReactNode {
  const searchId = useId();
  const personId = useId();
  const projectId = useId();
  const sourceId = useId();
  const sinceId = useId();
  const untilId = useId();

  const people = facets?.people ?? [];
  const projects = facets?.projects ?? [];
  const sources = facets?.sources ?? [];

  function set(key: keyof Narrowing, value: string): void {
    onChange({ ...draft, [key]: value });
  }

  return (
    /*
     * A form, so Enter submits. `role="search"` puts it in the landmark list.
     */
    <form className={styles.filters} onSubmit={onSubmit} role="search" aria-label="The feed">
      <div className={styles.searchRow}>
        <label className={styles.label} htmlFor={searchId}>
          Search what CAIRN has recorded
        </label>
        <div className={styles.searchControls}>
          <input
            id={searchId}
            className={styles.search}
            type="search"
            value={draft.q}
            placeholder="rate limiting, staging, the payments migration…"
            onChange={(event) => {
              set("q", event.target.value);
            }}
          />
          <Button type="submit" variant="primary">
            Search
          </Button>
        </div>
      </div>

      <div className={styles.controls}>
        {/* A filter is rendered only when there is something to put in it. */}
        {people.length > 0 && (
          <Choice
            id={personId}
            label="Person"
            value={draft.person}
            all="Everyone"
            options={people.map((person) => ({ value: person.id, label: person.name }))}
            onChange={(value) => {
              set("person", value);
            }}
          />
        )}

        {projects.length > 0 && (
          <Choice
            id={projectId}
            label="Project"
            value={draft.project}
            all="All projects"
            options={projects.map((project) => ({ value: project, label: project }))}
            onChange={(value) => {
              set("project", value);
            }}
          />
        )}

        {sources.length > 0 && (
          <Choice
            id={sourceId}
            label="Source"
            value={draft.source}
            all="All sources"
            options={sources.map((source) => ({
              value: source,
              label: SOURCE_LABELS[source] ?? source,
            }))}
            onChange={(value) => {
              set("source", value);
            }}
          />
        )}

        <div className={styles.control}>
          <label className={styles.label} htmlFor={sinceId}>
            From
          </label>
          <input
            id={sinceId}
            className={styles.date}
            type="date"
            value={draft.since}
            onChange={(event) => {
              set("since", event.target.value);
            }}
          />
        </div>

        <div className={styles.control}>
          <label className={styles.label} htmlFor={untilId}>
            To
          </label>
          <input
            id={untilId}
            className={styles.date}
            type="date"
            value={draft.until}
            onChange={(event) => {
              set("until", event.target.value);
            }}
          />
        </div>

        <div className={styles.actions}>
          <Button type="submit">Apply</Button>
          {showClear && (
            <Button type="button" variant="ghost" onClick={onClear}>
              Clear
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}

function Choice({
  id,
  label,
  value,
  all,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  all: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}): ReactNode {
  return (
    <div className={styles.control}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      {/* A native `<select>`: keyboard-operable, announced correctly, and on a
        phone it opens the platform picker. */}
      <select
        id={id}
        className={styles.select}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      >
        <option value="">{all}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The chronological feed: everything recorded, grouped by what kind of thing it is. */
function Stream({
  content,
  workspaceId,
  narrowing,
}: {
  content: ContentSource;
  workspaceId: string;
  narrowing: Narrowing;
}): ReactNode {
  const query = useMemo(() => asQuery(narrowing), [narrowing]);
  const load = useCallback(
    (signal: AbortSignal) => content.getFacts(workspaceId, query, signal),
    [content, workspaceId, query],
  );
  const { state, reload } = useAsync(load, "load the team feed");

  const [more, setMore] = useState<Fact[]>([]);
  /** Null until something has been paged. A bare `string | undefined` cannot
   * tell "not paged yet" from "paged, no more", and the feed then offers
   * "Show more" forever. */
  const [paged, setPaged] = useState<{ cursor: string | undefined } | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  // A new filter is a new list: without this, paged facts the current
  // narrowing excludes stay on screen.
  useEffect(() => {
    setMore([]);
    setPaged(null);
    setProblem(null);
  }, [query]);

  const next = paged ? paged.cursor : state.status === "ready" ? state.data.nextCursor : undefined;

  async function showMore(): Promise<void> {
    if (next === undefined) return;
    setLoadingMore(true);
    setProblem(null);
    try {
      const page = await content.getFacts(workspaceId, { ...query, cursor: next });
      setMore((current) => [...current, ...page.items]);
      setPaged({ cursor: page.nextCursor });
    } catch (error: unknown) {
      setProblem(describeError(error, "load more of the feed"));
    } finally {
      setLoadingMore(false);
    }
  }

  if (state.status === "loading") return <LoadingState label="the team feed" lines={4} />;
  if (state.status === "failed") {
    return <ErrorState title="The feed could not be loaded" error={state.error} onRetry={reload} />;
  }

  const facts = [...state.data.items, ...more];

  if (facts.length === 0) {
    return isNarrowed(narrowing) ? (
      <EmptyState title="Nothing matches these filters">
        CAIRN has activity for this workspace, but none of it matches what you asked for. Widening
        the dates is usually the one that helps.
      </EmptyState>
    ) : (
      <EmptyState title="Nothing recorded yet">
        CAIRN has not received any activity for this workspace. Connecting a source in Settings is
        what starts it — nothing is captured until someone turns it on.
      </EmptyState>
    );
  }

  return (
    <>
      <FeedSections facts={facts} />
      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}
      {next !== undefined && (
        <p className={styles.more}>
          <Button
            type="button"
            loading={loadingMore}
            onClick={() => {
              void showMore();
            }}
          >
            {loadingMore ? "Loading…" : "Show more"}
          </Button>
        </p>
      )}
    </>
  );
}

function FeedSections({ facts }: { facts: Fact[] }): ReactNode {
  return (
    <>
      {SECTIONS.map(({ kind, title }) => {
        const matching = facts.filter((fact) => fact.kind === kind);
        // Empty sections are omitted: a column of "0" headings reads as a
        // dashboard and says nothing.
        if (matching.length === 0) return null;

        return (
          <section className={styles.section} key={kind}>
            <h2 className={styles.sectionTitle}>
              {title}
              <span className={styles.count}>{matching.length}</span>
            </h2>
            <ClaimList claims={matching.map(toClaim)} label={title} />
          </section>
        );
      })}
    </>
  );
}

/**
 * Grouped by how they were found, never merged: a semantic near-miss shown in
 * the same list and style as an exact hit is believed more than it has earned.
 * No summary and no composed answer — every row is a stored fact with its
 * evidence, which is what grounding means here.
 */
function Results({
  content,
  workspaceId,
  narrowing,
}: {
  content: ContentSource;
  workspaceId: string;
  narrowing: Narrowing;
}): ReactNode {
  const query = useMemo(() => ({ ...asQuery(narrowing), q: narrowing.q }), [narrowing]);
  const load = useCallback(
    (signal: AbortSignal) => content.search(workspaceId, query, signal),
    [content, workspaceId, query],
  );
  const { state, reload } = useAsync(load, "search this workspace");

  if (state.status === "loading") return <LoadingState label="the results" lines={3} />;
  if (state.status === "failed") {
    return <ErrorState title="The search could not be run" error={state.error} onRetry={reload} />;
  }

  const items = state.data.items ?? [];
  const byWords = items.filter((hit) => hit.matchedOn === "words").map((hit) => hit.fact);
  const byMeaning = items.filter((hit) => hit.matchedOn === "meaning").map((hit) => hit.fact);

  if (items.length === 0) {
    return (
      <EmptyState title={`Nothing recorded matches “${narrowing.q}”`}>
        CAIRN only searches what it has recorded, so a word that never appeared in a pull request, a
        message or a meeting will not be here. Try the words the team actually used.
      </EmptyState>
    );
  }

  return (
    <>
      {byWords.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            Matched your words
            <span className={styles.count}>{byWords.length}</span>
          </h2>
          <ClaimList claims={byWords.map(toClaim)} label="Matched your words" />
        </section>
      )}

      {byMeaning.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            Found by meaning
            <span className={styles.count}>{byMeaning.length}</span>
          </h2>
          <p className={styles.note}>
            These do not contain what you typed. CAIRN found them by similarity, so they are a guess
            at what you meant — open the source to check.
          </p>
          <ClaimList claims={byMeaning.map(toClaim)} label="Found by meaning" />
        </section>
      )}

      {state.data.truncated && (
        <p className={styles.note}>
          These are the strongest matches, not all of them. Narrowing by project or date is the way
          to see the rest.
        </p>
      )}
    </>
  );
}
