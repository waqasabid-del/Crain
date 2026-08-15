import { CertaintyBadge } from "@cairn/ui";
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

export interface ClaimListProps {
  claims: Claim[];
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
        </li>
      ))}
    </ul>
  );
}
