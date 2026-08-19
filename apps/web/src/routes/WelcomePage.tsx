"use client";

import type { Consent, FactPage } from "@cairn/api-client";
import { Button, CertaintyBadge } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import type { Fact } from "../brief/types.js";
import { RoleChoice } from "../components/RoleChoice.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import { homeFor, homeLabelFor } from "../roles.js";
import utility from "../styles/utility.module.css";
import styles from "./WelcomePage.module.css";

/**
 * The screen a team member sees first — md/11 §4.1, and worker notification is
 * legally mandatory (md/05 §B.3.5). The order is the argument: their own record
 * first, then what CAIRN reads per source with the opt-out inline beside it
 * (never only a link to settings), then what CAIRN refuses to do. The words
 * "monitoring" and "tracking" are deliberately absent.
 *
 * Restyled to match the approved design, which shows "Your record" as two or
 * three example sentences rather than the full My Week screen. Rebuilt as its
 * own compact preview here — same real data (`myWeek`), same certainty badges
 * — with "Correct anything that's wrong" pointing at `/me` for the full
 * experience, rather than replacing real facts with the design's illustrative
 * copy or losing the correction feature by leaving it out.
 *
 * Still rendered inside the app's normal navigation shell ((app)/layout.tsx) —
 * the approved design's minimal topbar-only header is how its own static pages
 * are all drawn and isn't specific to this one, so removing the shell here
 * wasn't in scope for a single-page restyle.
 */
export function WelcomePage(): ReactNode {
  const { activeWorkspace, session, activeWorkRole } = useAuth();

  if (activeWorkspace === null) return <LoadingState label="your workspace" />;

  const name = session?.user.displayName ?? "";

  return (
    <div className={styles.page}>
      <div className={styles.intro}>
        <p className={styles.eyebrow}>Welcome to {activeWorkspace.name}</p>
        <h1 className={styles.title}>
          {name === "" ? "You’re on CAIRN" : `You’re on CAIRN, ${name}`}
        </h1>
        <p className={styles.lead}>
          CAIRN reads the work you already do — code, chat, the occasional meeting note — and keeps
          a plain-English picture of it up to date, so nobody has to update tickets by hand.
          It&rsquo;s here to speak up for your work, not to grade it. Nothing on this page is ever
          used against you.
        </p>
      </div>

      <hr className={styles.divider} />

      <YourRecord workspaceId={activeWorkspace.id} />

      <hr className={styles.divider} />

      <SourceControls workspaceId={activeWorkspace.id} />

      <hr className={styles.divider} />

      {/*
        Asked last, after the record and the controls. md/11 §6 gives each role
        a different first screen; asking first would make the first thing a form.
      */}
      <section className={styles.section} aria-labelledby="what-you-do">
        <h2 className={styles.heading} id="what-you-do">
          How do you spend your time?
        </h2>
        {/* No lead paragraph of its own here: `RoleChoice`'s own (non-compact,
          since this is a first-time context rather than Settings revisiting
          it) already says what needs saying — a second version beside it
          would just be the same reassurance twice. */}
        <RoleChoice />
      </section>

      <hr className={styles.divider} />

      <p className={styles.continue}>
        <Button asChild variant="primary">
          {/*
            Points wherever their answer points, and says where that is
            (md/11 §6). No answer falls back to the brief.
          */}
          <Link href={homeFor(activeWorkRole)}>Take me to {homeLabelFor(activeWorkRole)}</Link>
        </Button>
      </p>
    </div>
  );
}

function YourRecord({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<FactPage> => client.myWeek(workspaceId, undefined, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your record");

  return (
    <section className={styles.section} aria-labelledby="your-record">
      <h2 className={styles.heading} id="your-record">
        Your record
      </h2>
      <p className={styles.sectionLead}>
        Here&rsquo;s what CAIRN has noticed so far. If any of it is off, you get the first word.
      </p>

      {state.status === "loading" && <LoadingState label="your record" />}
      {state.status === "failed" && (
        <ErrorState title="CAIRN could not load your record" error={state.error} onRetry={reload} />
      )}
      {state.status === "ready" && <RecordPreview facts={state.data.items ?? []} />}
    </section>
  );
}

/** The first few facts, not the full week — a preview that points at `/me`
 * for the rest, rather than a second copy of that screen. */
function RecordPreview({ facts }: { facts: Fact[] }): ReactNode {
  if (facts.length === 0) {
    return (
      <EmptyState title="Nothing about you yet">
        CAIRN has not matched any activity to you yet. That usually just means it hasn&rsquo;t
        happened yet, not that something is missing.
      </EmptyState>
    );
  }

  const preview = facts.slice(0, 3);

  return (
    <>
      <div className={styles.recordPreview}>
        {preview.map((fact) => (
          <p key={fact.id} className={styles.recordStatement}>
            {fact.statement} <CertaintyBadge certainty={fact.certainty} />
          </p>
        ))}
      </div>
      <div className={styles.recordAction}>
        <Button asChild variant="secondary">
          <Link href="/me">Correct anything that&rsquo;s wrong</Link>
        </Button>
      </div>
    </>
  );
}

function GitHubIcon(): ReactNode {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.6 9.6 0 0 1 12 6.8c.85 0 1.7.11 2.5.33 1.9-1.29 2.74-1.02 2.74-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z" />
    </svg>
  );
}

/** A generic source icon for anything that isn't GitHub — chat, meetings,
 * documents. One shape rather than a growing icon-per-source switch, since
 * this page does not need to distinguish them visually the way the source's
 * own name and description already do. */
function GenericSourceIcon(): ReactNode {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 8h18" />
    </svg>
  );
}

function SourceControls({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Consent> => client.mySources(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your privacy choices");

  if (state.status === "loading") return <LoadingState label="your choices" />;
  if (state.status === "failed") {
    return (
      <ErrorState title="CAIRN could not load your choices" error={state.error} onRetry={reload} />
    );
  }

  return (
    <>
      <section className={styles.section} aria-labelledby="what-cairn-reads">
        <h2 className={styles.heading} id="what-cairn-reads">
          What CAIRN reads — and what you can switch off
        </h2>
        <p className={styles.sectionLead}>
          None of this is mandatory. Turn off any source and CAIRN simply stops reading it for you.
        </p>
        <div className={styles.panel}>
          {(state.data.sources ?? []).map((source) => (
            <SourceToggle key={source.source} workspaceId={workspaceId} source={source} />
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="never">
        <h2 className={styles.heading} id="never">
          What CAIRN never does
        </h2>
        <ul className={styles.refusals}>
          {(state.data.refusals ?? []).map((refusal) => (
            <li key={refusal}>{refusal}</li>
          ))}
        </ul>
      </section>
    </>
  );
}

function SourceToggle({
  workspaceId,
  source,
}: {
  workspaceId: string;
  source: NonNullable<Consent["sources"]>[number];
}): ReactNode {
  const client = useApiClient();
  const id = useId();

  const [optedOut, setOptedOut] = useState(source.optedOut);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  async function change(next: boolean): Promise<void> {
    setBusy(true);
    setProblem(null);
    try {
      const result = await client.setSourceConsent(workspaceId, {
        source: source.source,
        optedOut: next,
      });
      setOptedOut(next);
      // The count is reported: a toggle that visibly did something is one a
      // person believes.
      setNote(
        next
          ? result.unlinked > 0
            ? `Done. ${String(result.unlinked)} ${result.unlinked === 1 ? "thing is" : "things are"} no longer attributed to you.`
            : "Done. Nothing from this source is attributed to you."
          : "Attribution from this source starts again from today. Anything removed earlier stays removed.",
      );
    } catch (error: unknown) {
      setProblem(describeError(error, "save your choice"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.sourceRow}>
      <div className={styles.sourceHeader}>
        <span className={styles.sourceIcon} aria-hidden="true">
          {source.source === "github" ? <GitHubIcon /> : <GenericSourceIcon />}
        </span>
        <div>
          <p className={styles.sourceName}>{source.label}</p>
          <p className={styles.sourceReads}>{source.reads}</p>
        </div>
      </div>

      {/*
        A native checkbox styled to look like a switch — still correctly
        announced and keyboard-operable everywhere, which is the property
        that actually matters here; only its appearance changes. The
        explicit label stays for anyone using a screen reader, since the
        icon and description beside it carry no meaning on their own without
        it — just not shown to sighted readers, who already have both.
      */}
      <span className={styles.switch}>
        <input
          id={id}
          className={styles.switchInput}
          type="checkbox"
          checked={optedOut}
          disabled={busy}
          onChange={(event) => {
            void change(event.target.checked);
          }}
        />
        <label className={utility.visuallyHidden} htmlFor={id}>
          Do not attribute {source.label} to me
        </label>
      </span>

      {note !== null && (
        <p className={styles.note} role="status">
          {note}
        </p>
      )}
      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}
    </div>
  );
}
