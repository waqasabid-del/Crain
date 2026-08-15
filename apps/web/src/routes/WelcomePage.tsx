"use client";

import type { Consent } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { RoleChoice } from "../components/RoleChoice.js";
import { ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import { homeFor, homeLabelFor } from "../roles.js";
import { MyWeekPage } from "./MyWeekPage.js";
import styles from "./WelcomePage.module.css";

/**
 * The screen a team member sees first — md/11 §4.1, and worker notification is
 * legally mandatory (md/05 §B.3.5). The order is the argument: their own record
 * first, then what CAIRN reads per source with the opt-out inline beside it
 * (never only a link to settings), then what CAIRN refuses to do. The words
 * "monitoring" and "tracking" are deliberately absent.
 */
export function WelcomePage(): ReactNode {
  const { activeWorkspace, session, activeWorkRole } = useAuth();

  if (activeWorkspace === null) return <LoadingState label="your workspace" />;

  const name = session?.user.displayName ?? "";

  return (
    <div className={styles.page}>
      <PageHeader
        title={name === "" ? "Welcome to CAIRN" : `Welcome, ${name}`}
        description="CAIRN writes up your team's week from the work you already do. This is your record of it — and it is yours to correct."
      />

      {/* The record first: everything below it is context for something already seen. */}
      <section className={styles.section} aria-labelledby="your-record">
        <h2 className={styles.heading} id="your-record">
          What CAIRN has about you so far
        </h2>
        <MyWeekPage />
      </section>

      <SourceControls workspaceId={activeWorkspace.id} />

      {/*
        Asked last, after the record and the controls. md/11 §6 gives each role
        a different first screen; asking first would make the first thing a form.
      */}
      <section className={styles.section} aria-labelledby="what-you-do">
        <h2 className={styles.heading} id="what-you-do">
          What CAIRN opens on
        </h2>
        <RoleChoice />
      </section>

      <p className={styles.continue}>
        <Button asChild variant="primary">
          {/*
            Points wherever their answer points, and says where that is
            (md/11 §6). No answer falls back to the brief.
          */}
          <Link href={homeFor(activeWorkRole)}>Go to {homeLabelFor(activeWorkRole)}</Link>
        </Button>
      </p>
    </div>
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
          What CAIRN reads, and what you can switch off
        </h2>
        <p className={styles.lead}>
          Every source is listed, including ones your workspace has not connected. You can decide
          about them now.
        </p>
        <ul className={styles.sources}>
          {(state.data.sources ?? []).map((source) => (
            <li key={source.source} className={styles.source}>
              <SourceToggle workspaceId={workspaceId} source={source} />
            </li>
          ))}
        </ul>
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
    <>
      <div className={styles.sourceHeader}>
        <div>
          {/*
            The source name is not the checkbox's label. The label below names
            the action *and* the source, so each control is self-describing in a
            screen reader's control list.
          */}
          <p className={styles.sourceName}>{source.label}</p>
          <p className={styles.sourceReads}>{source.reads}</p>
        </div>

        {/*
          A native checkbox, not a styled switch: correctly announced and
          keyboard-operable everywhere. Here an unusable control is a consent
          failure, not just a usability one.
        */}
        <span className={styles.control}>
          <input
            id={id}
            className={styles.checkbox}
            type="checkbox"
            checked={optedOut}
            disabled={busy}
            onChange={(event) => {
              void change(event.target.checked);
            }}
          />
          <label className={styles.controlLabel} htmlFor={id}>
            Do not attribute {source.label} to me
          </label>
        </span>
      </div>

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
    </>
  );
}
