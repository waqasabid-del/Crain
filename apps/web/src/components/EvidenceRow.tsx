import { CertaintyBadge } from "@cairn/ui";
import type { ReactNode } from "react";

import type { Fact } from "../brief/types.js";
import styles from "./EvidenceRow.module.css";

/** How many source chips fit before the row starts reading as a list of links
 * rather than a line of provenance. The rest collapse into one "+N". */
const MAX_SOURCE_CHIPS = 2;

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** Past a week, "9d ago" stops helping and a date starts. */
const RELATIVE_HORIZON_DAYS = 7;

/**
 * A short, human distance from now.
 *
 * Relative only while it is still the more useful answer: inside a week the
 * reader is asking "recently?", beyond it they are asking "when?". Pure and
 * `now`-injectable so the boundaries can be tested without freezing the clock.
 *
 * Returns "" for a date that will not parse — the caller renders nothing rather
 * than "Invalid Date", because a broken timestamp is not evidence.
 */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const thenMs = then.getTime();
  if (Number.isNaN(thenMs)) return "";

  // A clock-skewed future stamp reads as the present, not as a negative age.
  const elapsed = Math.max(now.getTime() - thenMs, 0);

  if (elapsed < MINUTE_MS) return "just now";
  if (elapsed < HOUR_MS) return `${String(Math.floor(elapsed / MINUTE_MS))}m ago`;
  if (elapsed < DAY_MS) return `${String(Math.floor(elapsed / HOUR_MS))}h ago`;

  const days = Math.floor(elapsed / DAY_MS);
  if (days === 1) return "yesterday";
  if (days <= RELATIVE_HORIZON_DAYS) return `${String(days)}d ago`;

  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export interface EvidenceRowProps {
  fact: Fact;
  /** The mention above the statement. Off inside a person's own view, where
   * repeating their name on every row says nothing. */
  showPerson?: boolean | undefined;
}

/**
 * One piece of evidence: a statement, then the line that lets somebody check it.
 *
 * Structured rather than prose. The old row set the statement and its metadata
 * in one paragraph, so certainty, source and time all read as part of the
 * sentence — the reader had to parse English to find the citation. Here the
 * statement owns line one at the prose measure, and everything that qualifies it
 * sits on line two at `--text-xs`.
 *
 * The mention is a credit line and nothing more: no link to a profile, no count
 * beside it, no ordering. A name that clicks through to a page of totals is the
 * shape this product refuses (md/05 §B.1), and the cheapest place to
 * accidentally build it is a row like this one.
 */
export function EvidenceRow({ fact, showPerson = true }: EvidenceRowProps): ReactNode {
  const sources = fact.sources ?? [];
  const shown = sources.slice(0, MAX_SOURCE_CHIPS);
  const overflow = sources.length - shown.length;

  const mention = showPerson ? fact.people?.[0]?.mention : undefined;

  const occurredAt = fact.occurredAt;
  const when = occurredAt === undefined || occurredAt === null ? "" : relativeTime(occurredAt);

  return (
    <article className={styles.row}>
      <p className={styles.statement}>{fact.statement}</p>
      <div className={styles.meta}>
        {mention !== undefined && <span className={styles.mention}>{mention}</span>}
        <CertaintyBadge certainty={fact.certainty} />
        {shown.map((source) =>
          // Linked and unlinked chips share every style. An unlinked citation is
          // still provenance a person can go and check; making it look faded
          // would tell the reader it counts for less.
          source.url === undefined || source.url === null ? (
            <span key={source.evidenceId} className={styles.chip}>
              {source.source}
            </span>
          ) : (
            <a
              key={source.evidenceId}
              className={styles.chip}
              href={source.url}
              target="_blank"
              rel="noreferrer"
            >
              {source.source}
            </a>
          ),
        )}
        {overflow > 0 && <span className={styles.chip}>{`+${String(overflow)}`}</span>}
        {when !== "" && occurredAt !== undefined && occurredAt !== null && (
          <time className={styles.time} dateTime={occurredAt}>
            {when}
          </time>
        )}
      </div>
    </article>
  );
}
