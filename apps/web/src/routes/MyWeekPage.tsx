"use client";

import { ApiError, type CorrectionBody, type FactPage } from "@cairn/api-client";
import { Button, CertaintyBadge } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { recordLeadFor } from "../roles.js";
import type { Fact } from "../brief/types.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./MyWeekPage.module.css";

/**
 * My Week — the reader's own record, and the place they can change it.
 *
 * md/05 §B.2.3 commits to **employee-owned records**, and this screen is where
 * that stops being a policy sentence. Two things follow from it and neither is
 * decoration:
 *
 * **Correction is one action, not a form.** md/09 §9 calls correction an
 * *input*: a person who was there disagreeing with a machine is the strongest
 * evidence the system holds. Four buttons, each a complete statement — and only
 * the one that genuinely needs wording asks for any.
 *
 * **The screen says what CAIRN believes, not what the reader achieved.** No
 * counts, no streaks, no comparison. CAIRN sits close to the line between
 * coordination software and workplace monitoring (md/05 §B.1), and a personal
 * page with a number on it is the single fastest way to cross it.
 */
export function MyWeekPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) return <LoadingState label="your workspace" shape="rows" />;
  return <WorkspaceWeek workspaceId={activeWorkspace.id} />;
}

function WorkspaceWeek({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const { activeWorkRole } = useAuth();
  const load = useCallback(
    (signal: AbortSignal): Promise<FactPage> => client.myWeek(workspaceId, undefined, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your record");

  return (
    <>
      {/*
        The lead sentence follows what the reader said they do (md/11 §6).
        For a designer it *is* the feature: md/08 §A.4 identifies feeling
        invisible as a real adoption risk, and a first screen that opens by
        talking about commits has already told them whose product this is.
        The default mentions neither code nor design, because it is what
        somebody sees before CAIRN knows anything about them.
      */}
      <PageHeader
        eyebrow="This week"
        title="Your record"
        description={recordLeadFor(activeWorkRole)}
        actions={
          <Link className={utility.actionLink} href="/trust">
            Trust Center
          </Link>
        }
      />

      {state.status === "loading" && <LoadingState label="your record" shape="rows" lines={4} />}

      {state.status === "failed" && (
        <ErrorState
          title="Your record could not be loaded"
          error={state.error}
          onRetry={reload}
          action={
            <Link className={utility.actionLink} href="/trust">
              What CAIRN records about you
            </Link>
          }
        />
      )}

      {state.status === "ready" && (
        <MyFacts workspaceId={workspaceId} facts={state.data.items ?? []} onChanged={reload} />
      )}
    </>
  );
}

function MyFacts({
  workspaceId,
  facts,
  onChanged,
}: {
  workspaceId: string;
  facts: Fact[];
  onChanged: () => void;
}): ReactNode {
  if (facts.length === 0) {
    return (
      <EmptyState
        title="Nothing about you yet"
        action={
          <Link className={utility.actionLink} href="/feed">
            See the team&rsquo;s activity
          </Link>
        }
      >
        CAIRN has not matched any activity to you this week. Almost always that means the address on
        your commits is not one it knows about yet, rather than a quiet week — an admin can link it
        in Workspace settings.
      </EmptyState>
    );
  }

  return (
    <ul className={styles.list} aria-label="What CAIRN believes about you">
      {facts.map((fact) => (
        <li key={fact.id} className={styles.item}>
          <FactRow workspaceId={workspaceId} fact={fact} onChanged={onChanged} />
        </li>
      ))}
    </ul>
  );
}

/** The four things a person can say, and what each of them means. */
const CORRECTIONS = [
  { kind: "reworded", label: "Fix the wording", needsText: true },
  { kind: "wrong_person", label: "That was not me", needsText: false },
  { kind: "did_not_happen", label: "This did not happen", needsText: false },
  { kind: "no_longer_true", label: "No longer true", needsText: false },
] as const;

function FactRow({
  workspaceId,
  fact,
  onChanged,
}: {
  workspaceId: string;
  fact: Fact;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const fieldId = useId();

  const [open, setOpen] = useState(false);
  const [rewording, setRewording] = useState(fact.statement);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  /** Whether the refusal is one that will be repeated forever. See `send`. */
  const [permanent, setPermanent] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function send(body: CorrectionBody): Promise<void> {
    setBusy(true);
    setProblem(null);
    setPermanent(false);
    try {
      await client.correctFact(workspaceId, fact.id, body);
      // Confirmed in words before the list refreshes. A row that simply
      // vanishes leaves the reader unsure whether their correction was
      // recorded or the page merely moved.
      setDone("Recorded. Your correction is part of your record now, and CAIRN treats it as fact.");
      onChanged();
    } catch (error: unknown) {
      setProblem(describeError(error, "record your correction"));
      // A refusal is not an outage. Trying again cannot change a permission,
      // and a screen that implies it can costs somebody an afternoon before
      // they think to ask an admin instead.
      setPermanent(error instanceof ApiError && (error.status === 403 || error.status === 404));
    } finally {
      setBusy(false);
    }
  }

  function handleRewording(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void send({ kind: "reworded", statement: rewording });
  }

  return (
    <>
      <p className={styles.statement}>{fact.statement}</p>

      <div className={styles.meta}>
        <CertaintyBadge certainty={fact.certainty} />
        {(fact.sources ?? []).map((source) =>
          source.url == null ? (
            <span key={source.evidenceId} className={styles.source}>
              {source.evidenceId}
            </span>
          ) : (
            <a
              key={source.evidenceId}
              className={styles.source}
              href={source.url}
              target="_blank"
              rel="noreferrer"
            >
              {source.evidenceId}
            </a>
          ),
        )}
        {done === null && (
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            onClick={() => {
              setOpen((was) => !was);
            }}
          >
            {/*
              Named for the claim it corrects. A screen-reader user navigating
              by control list would otherwise hear a page of identical "Not
              right?" buttons with no way to tell them apart.
            */}
            Not right?
            <span className={utility.visuallyHidden}> — {fact.statement}</span>
          </Button>
        )}
      </div>

      {done !== null && (
        <p className={styles.done} role="status">
          {done}
        </p>
      )}

      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
          {permanent && (
            <>
              {" "}
              Trying again will not change it — a workspace admin can, or CAIRN support can be given
              the reference below.
            </>
          )}
          {problem.requestId !== undefined && (
            <span className={styles.reference}>Reference: {problem.requestId}</span>
          )}
        </p>
      )}

      {open && done === null && (
        <div className={styles.corrections}>
          {CORRECTIONS.filter((option) => !option.needsText).map((option) => (
            <Button
              key={option.kind}
              variant="secondary"
              size="sm"
              loading={busy}
              onClick={() => {
                void send({ kind: option.kind });
              }}
            >
              {option.label}
            </Button>
          ))}

          <form className={styles.rewordForm} onSubmit={handleRewording}>
            <label className={styles.rewordLabel} htmlFor={fieldId}>
              Or say what it should have said
            </label>
            <textarea
              id={fieldId}
              className={styles.reword}
              value={rewording}
              rows={2}
              onChange={(event) => {
                setRewording(event.target.value);
              }}
            />
            <Button type="submit" variant="primary" size="sm" loading={busy}>
              Save correction
            </Button>
          </form>
        </div>
      )}
    </>
  );
}
