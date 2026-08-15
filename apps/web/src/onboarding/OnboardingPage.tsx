"use client";

import type { Onboarding } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { ErrorState, LoadingState } from "../components/States.js";
import { PageHeader } from "../components/PageHeader.js";
import { describeError, type DescribedError } from "../errors.js";
import { githubInstallUrl } from "./install.js";
import styles from "./OnboardingPage.module.css";

/**
 * The first ten minutes. The requirement is never an empty state (md/11 §3,
 * Step 20), so every number here is a real counter from the API. No percentages:
 * GitHub does not say how many commits a repository holds before it is walked,
 * so any percentage would be invented.
 */

/** Fast enough that the counters visibly move, slow enough that a ten-minute
 * import costs hundreds of requests rather than thousands. Stops when the
 * import finishes, so an abandoned tab is not a polling loop. */
const POLL_INTERVAL_MS = 3_000;

export function OnboardingPage(): ReactNode {
  const client = useApiClient();
  const { activeWorkspace } = useAuth();
  const workspaceId = activeWorkspace?.id ?? null;

  const [state, setState] = useState<Onboarding | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  // A ref, not state: in state this would restart the effect on every tick,
  // giving one new interval per response.
  const importing = useRef(false);

  const load = useCallback(async (): Promise<void> => {
    if (workspaceId === null) return;
    try {
      const next = await client.getOnboarding(workspaceId);
      setState(next);
      setProblem(null);
      importing.current = next.importing;
    } catch (error: unknown) {
      setProblem(describeError(error, "check how the import is going"));
      // Polling stops on error rather than hammering a failing endpoint.
      importing.current = false;
    }
  }, [client, workspaceId]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (!importing.current) return;
      void load();
    }, POLL_INTERVAL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [load]);

  if (workspaceId === null) return <LoadingState label="your workspace" />;

  if (problem !== null && state === null) {
    return (
      <ErrorState
        title="CAIRN could not check your workspace"
        error={problem}
        onRetry={() => {
          void load();
        }}
      />
    );
  }

  if (state === null) return <LoadingState label="your workspace" />;

  return (
    <div className={styles.page}>
      <PageHeader
        title={TITLES[state.stage] ?? "Setting up"}
        description={DESCRIPTIONS[state.stage] ?? ""}
      />
      {state.stage === "not_connected" ? <ConnectStep /> : <ImportStep state={state} />}
    </div>
  );
}

/** Headings say where the reader is, not what the job queue is doing. */
const TITLES: Record<string, string> = {
  not_connected: "Connect your code",
  importing: "Reading your history",
  understanding: "Reading your history",
  ready: "Your workspace is ready",
};

const DESCRIPTIONS: Record<string, string> = {
  not_connected: "CAIRN needs one source to start from. GitHub takes about a minute to connect.",
  importing: "This usually takes a few minutes. You can leave this page — it keeps going.",
  understanding: "This usually takes a few minutes. You can leave this page — it keeps going.",
  ready: "Everything from here happens as your team works.",
};

function ConnectStep(): ReactNode {
  return (
    <section className={styles.card}>
      <h2 className={styles.cardTitle}>Connect GitHub</h2>
      <p className={styles.cardBody}>
        CAIRN reads commits, pull requests and reviews to work out what happened. It never reads
        your source code, and you choose which repositories it can see.
      </p>
      {/* An anchor, not a click handler: this is a navigation to GitHub's own
        consent screen, and an admin wants to inspect the destination first. */}
      <Button asChild variant="primary">
        <a href={githubInstallUrl()} rel="noopener">
          Connect GitHub
        </a>
      </Button>
      <p className={styles.aside}>
        You need admin access to the organisation to install it. If you do not, invite whoever does
        — they can connect it and you keep the workspace.
      </p>
    </section>
  );
}

function ImportStep({ state }: { state: Onboarding }): ReactNode {
  // Defaulted, not asserted: the generated type marks every field optional.
  const repositories = state.repositories ?? [];
  const finished = repositories.filter((repository) => repository.finished).length;

  return (
    <>
      {/* The counters are what stops the screen being empty. */}
      <section className={styles.card} aria-live="polite">
        <h2 className={styles.cardTitle}>
          {state.accountLogin == null
            ? "Reading your repositories"
            : `Reading ${state.accountLogin}`}
        </h2>
        <dl className={styles.counters}>
          <div className={styles.counter}>
            <dt>Commits read</dt>
            <dd>{state.commitsImported.toLocaleString()}</dd>
          </div>
          <div className={styles.counter}>
            <dt>Repositories</dt>
            <dd>
              {finished} of {repositories.length}
            </dd>
          </div>
          <div className={styles.counter}>
            <dt>Facts found</dt>
            <dd>{state.factsAvailable.toLocaleString()}</dd>
          </div>
        </dl>

        {repositories.length > 0 && (
          <ul className={styles.repositories}>
            {repositories.map((repository) => (
              <li key={repository.repository} className={styles.repository}>
                <span className={styles.repositoryName}>{repository.repository}</span>
                <span className={styles.repositoryState}>
                  {repository.finished
                    ? "Done"
                    : `${repository.commitsImported.toLocaleString()} commits`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Offered as soon as there is anything to read: the promise is ten
        minutes to first output, not to a completed import. */}
      {state.factsAvailable > 0 && (
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>There is already something to read</h2>
          <p className={styles.cardBody}>
            CAIRN has understood {state.factsAvailable.toLocaleString()} things so far. The rest
            keeps arriving in the background.
          </p>
          <Button asChild variant="primary">
            <Link href="/">Open your brief</Link>
          </Button>
        </section>
      )}

      {!state.importing && state.factsAvailable === 0 && (
        <section className={styles.card}>
          <h2 className={styles.cardTitle}>Nothing to summarise yet</h2>
          <p className={styles.cardBody}>
            CAIRN read your repositories and found no activity in the period it imported. That is a
            real answer rather than a problem — the brief appears as your team works.
          </p>
        </section>
      )}
    </>
  );
}
