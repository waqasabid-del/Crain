"use client";

import type { RelatedWork } from "@cairn/api-client";
import { CertaintyBadge, type Certainty } from "@cairn/ui";
import { useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import utility from "../styles/utility.module.css";
import { CapacityChip } from "./CapacityChip.js";
import styles from "./RelatedWorkFinder.module.css";

/**
 * "Who has touched something like this?" — answered with evidence, and only
 * evidence.
 *
 * What this deliberately is not: a ranking, a recommender, an allocator. The
 * API returns cited facts grouped by the person they credit, ordered by most
 * recent related fact — a property of the evidence, and the screen says so in
 * those words. There is no score to render because no score exists in the
 * response; capacity beside each name is the person's own statement, chipped
 * as self-reported. The reader weighs the evidence and decides — CAIRN's job
 * ends at showing its citations (module docstring of
 * `api/routers/related_work.py`, mirrored in the Trust Center).
 */
export function RelatedWorkFinder({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const inputId = useId();
  const [topic, setTopic] = useState("");
  const [state, setState] = useState<
    | { status: "idle" }
    | { status: "searching" }
    | { status: "failed"; error: DescribedError }
    | { status: "ready"; results: RelatedWork }
  >({ status: "idle" });

  async function search(): Promise<void> {
    const trimmed = topic.trim();
    if (trimmed.length < 2) return;
    setState({ status: "searching" });
    try {
      const results = await client.findRelatedWork(workspaceId, trimmed);
      setState({ status: "ready", results });
    } catch (error: unknown) {
      setState({ status: "failed", error: describeError(error, "search related work") });
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void search();
  }

  return (
    <section className={styles.section} aria-labelledby={`${inputId}-heading`}>
      <h2 id={`${inputId}-heading`} className={styles.heading}>
        Find related work
      </h2>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={utility.visuallyHidden} htmlFor={inputId}>
          Task or topic to find related work for
        </label>
        <input
          id={inputId}
          className={styles.input}
          type="search"
          value={topic}
          onChange={(event) => {
            setTopic(event.target.value);
          }}
          placeholder="e.g. rate limiting on the public API"
          maxLength={500}
        />
        <button
          className={styles.button}
          type="submit"
          disabled={state.status === "searching" || topic.trim().length < 2}
        >
          {/* "Find related work", not "Search": this now sits on the Activity
            page, which already has a Search button for the feed's own filters.
            Two buttons with one name is what a screen-reader user hears as
            "Search, Search" with no way to tell which does what. */}
          {state.status === "searching" ? "Searching…" : "Find related work"}
        </button>
      </form>

      {/* Announced: the result of the reader's own action. */}
      <div aria-live="polite">
        {state.status === "failed" && (
          <p role="alert" className={styles.error}>
            {state.error.message}
          </p>
        )}

        {state.status === "ready" && state.results.groups.length === 0 && (
          <p className={styles.empty}>
            No recorded work matched that. Absence here is not a fact about anyone — it only means
            no cited fact matched the words you used. Try different words, or a narrower task.
          </p>
        )}

        {state.status === "ready" && state.results.groups.length > 0 && (
          <ul className={styles.groups} aria-label="People with related work, newest first">
            {state.results.groups.map((group) => (
              <li key={group.personId} className={styles.group}>
                <div className={styles.person}>
                  <span className={styles.personName}>{group.displayName}</span>
                  <CapacityChip capacity={group.capacity} />
                </div>
                <ul className={styles.facts} aria-label={`Related work by ${group.displayName}`}>
                  {group.facts.map((fact, index) => (
                    <li key={`${group.personId}-${String(index)}`} className={styles.fact}>
                      <div className={styles.factHeader}>
                        <CertaintyBadge certainty={fact.certainty as Certainty} />
                        {fact.occurredAt != null && (
                          <time className={styles.when} dateTime={fact.occurredAt}>
                            {formatDate(fact.occurredAt)}
                          </time>
                        )}
                      </div>
                      <p className={styles.statement}>{fact.statement}</p>
                      <ul className={styles.sources} aria-label="Sources">
                        {fact.sources.map((source) =>
                          source.url == null ? (
                            <li key={source.evidenceId} className={styles.sourcePlain}>
                              {source.evidenceId}
                            </li>
                          ) : (
                            <li key={source.evidenceId}>
                              <a
                                className={styles.sourceLink}
                                href={source.url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {source.evidenceId}
                                <span className={utility.visuallyHidden}>
                                  {" "}
                                  (opens in a new tab)
                                </span>
                              </a>
                            </li>
                          ),
                        )}
                      </ul>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
