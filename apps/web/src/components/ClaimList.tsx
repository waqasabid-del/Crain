import { CertaintyBadge } from "@cairn/ui";
import clsx from "clsx";
import type { ReactNode } from "react";

import type { Claim, SourceRef } from "../brief/types.js";
import utility from "../styles/utility.module.css";
import styles from "./ClaimList.module.css";

const SOURCE_LABELS: Record<string, string> = {
  github: "GitHub",
  chat: "Chat",
  meeting: "Meeting",
  document: "Document",
};

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

/** A native `<details>`: keyboard operation and the expanded announcement come
 * free. Collapsed — a source must be reachable, not printed. */
function Citations({ claim }: { claim: Claim }): ReactNode {
  // Defaulted, not asserted: the API marks the array optional.
  const citations = claim.citations ?? [];
  const count = citations.length;

  return (
    <details className={styles.sources}>
      <summary className={styles.summary}>
        {/* The claim text is in the accessible name: a control list of identical
          "1 source" summaries is unusable. */}
        <span className={utility.visuallyHidden}>Sources for: {claim.text}</span>
        <span aria-hidden="true">
          {count} {count === 1 ? "source" : "sources"}
        </span>
        <svg
          className={styles.caret}
          width="10"
          height="10"
          viewBox="0 0 10 10"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      </summary>

      <ul className={styles.citations}>
        {citations.map((citation) => (
          <li key={citation.evidenceId}>
            <Citation citation={citation} />
          </li>
        ))}
      </ul>
    </details>
  );
}

function Citation({ citation }: { citation: SourceRef }): ReactNode {
  const label = sourceLabel(citation.source);

  return (
    <>
      <div className={styles.citationSource}>{label}</div>
      {citation.url == null ? (
        // Shown unlinked rather than dropped: a hidden citation silently breaks
        // the promise the feature rests on.
        <span className={styles.citationUnlinked}>
          {citation.evidenceId} — no link available for this source
        </span>
      ) : (
        <a
          className={styles.citationLink}
          href={citation.url}
          // `noreferrer` with `_blank` guards the `window.opener` hijack on
          // links whose host is customer-supplied.
          target="_blank"
          rel="noreferrer"
        >
          {citation.evidenceId}
          <span className={utility.visuallyHidden}> (opens in a new tab)</span>
        </a>
      )}
      {citation.quote != null && <blockquote className={styles.quote}>{citation.quote}</blockquote>}
    </>
  );
}

/**
 * How many provider accounts stand behind one statement, and whether CAIRN can
 * place them — counts only, never the accounts.
 *
 * The links underneath carry Slack `U…` and Google Chat `users/…` identifiers.
 * Those are private provider ids: the API filters them out of `people`
 * altogether, because publishing one as a credit would identify a colleague by
 * a handle they never chose to share. But dropping them without trace leaves a
 * reader unable to tell *nobody else was involved* from *somebody was, and
 * CAIRN cannot yet say who* — and to a person checking whether their own record
 * is complete those are entirely different answers. The number is the honest
 * middle, and it is the only thing this component is ever given.
 *
 * It is a property of one statement, never of a person. Nothing here may be
 * summed across facts, sorted, or shown beside a name: md/05 §B.3.3 makes a
 * per-person tally a product-reclassifying feature rather than a style choice.
 */
export interface Attribution {
  /** Accounts behind this fact that the identity graph has linked to a person. */
  resolvedActors: number;
  /** …and that it has not linked yet. */
  unresolvedActors: number;
}

/** A claim, optionally carrying the attribution counts for the fact behind it.
 * An intersection rather than a new shape, so a screen with nothing to say
 * about attribution — the Brief — passes a plain `Claim` and is unaffected. */
export type ClaimEntry = Claim & { attribution?: Attribution };

/** Small numbers as words, so the note reads as a sentence rather than a
 * readout. Larger ones stay numeric: "seventeen contributors" is worse. */
const NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];

function inWords(count: number): string {
  return NUMBER_WORDS[count] ?? String(count);
}

function sentenceCase(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export interface AttributionNoteProps {
  attribution: Attribution | undefined;
  className?: string;
}

/**
 * What CAIRN can and cannot say about who is behind a statement.
 *
 * Two deliberate choices in the wording of the unresolved case. It is not
 * phrased as a failure — the reader did nothing, and a screen that reads like a
 * defect notice teaches people to distrust the record rather than to finish
 * connecting it. And it is not phrased as concealment: "has not connected their
 * account yet" is a neutral, temporary, ordinary state of affairs, which is
 * what it is.
 *
 * No `role="status"`: this is on screen from first paint, describing content
 * that is already there. A live region announcing a fact nobody just changed is
 * noise a screen reader user cannot switch off.
 */
export function AttributionNote({ attribution, className }: AttributionNoteProps): ReactNode {
  const resolved = attribution?.resolvedActors ?? 0;
  const unresolved = attribution?.unresolvedActors ?? 0;

  // Nothing to attribute. Silence, rather than a sentence announcing an absence
  // — "no connected accounts" is a state the product does not have.
  if (resolved <= 0 && unresolved <= 0) return null;

  return (
    <p className={clsx(styles.attribution, className)}>
      {resolved > 0 &&
        (resolved === 1
          ? "Attributed through a connected account."
          : `Attributed through ${inWords(resolved)} connected accounts.`)}
      {resolved > 0 && unresolved > 0 && " "}
      {unresolved > 0 &&
        (unresolved === 1
          ? "One contributor here has not connected their account to CAIRN yet, so CAIRN cannot name them."
          : `${sentenceCase(inWords(unresolved))} contributors here have not connected their accounts to CAIRN yet, so CAIRN cannot name them.`)}
    </p>
  );
}

export interface ClaimListProps {
  claims: ClaimEntry[];
  label: string;
}

/**
 * Every claim carries a `CertaintyBadge`, categorical and never numeric
 * (md/05 §A.2), and its citations — provenance on uncertain claims is a shipping
 * gate (md/05 §B.7).
 */
export function ClaimList({ claims, label }: ClaimListProps): ReactNode {
  return (
    // A list, so the count is announced. Labelled: several can share a page.
    <ul className={styles.list} aria-label={label}>
      {claims.map((claim, index) => (
        // Positional keys: an ordered list with no identifier, never reordered.
        <li key={index} className={styles.claim}>
          <p className={styles.text}>{claim.text}</p>
          <div className={styles.footer}>
            <CertaintyBadge certainty={claim.certainty} />
            {(claim.credits ?? []).length > 0 && (
              <span className={styles.credits}>{(claim.credits ?? []).join(", ")}</span>
            )}
            <Citations claim={claim} />
          </div>
          {/* Outside the footer, on its own line: it is a sentence, and a
            sentence wrapping between a badge and a disclosure control reads as
            a caption for whichever of them it landed next to. */}
          <AttributionNote attribution={claim.attribution} />
        </li>
      ))}
    </ul>
  );
}
