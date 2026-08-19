"use client";

import type { Onboarding } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type SyntheticEvent,
} from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { describeError, type DescribedError } from "../errors.js";
import { githubInstallUrl } from "./install.js";
import utility from "../styles/utility.module.css";
import styles from "./OnboardingPage.module.css";

/**
 * The first ten minutes. The requirement is never an empty state (md/11 §3,
 * Step 20), so every number here is a real counter from the API. No percentages:
 * GitHub does not say how many commits a repository holds before it is walked,
 * so any percentage would be invented.
 *
 * Restyled as the approved design's three-step checklist rather than the
 * stage-keyed single card this used to be — same real data underneath
 * (`getOnboarding`, the same poll), just all three steps visible together
 * with their real status instead of one stage's card at a time.
 */

/** Fast enough that the counters visibly move, slow enough that a ten-minute
 * import costs hundreds of requests rather than thousands. Stops when the
 * import finishes, so an abandoned tab is not a polling loop. */
const POLL_INTERVAL_MS = 3_000;

function CircleIcon(): ReactNode {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

function CheckCircleIcon(): ReactNode {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.5 2.5 4.5-5" />
    </svg>
  );
}

function LockIcon(): ReactNode {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="4" y="10" width="16" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function GitHubIcon(): ReactNode {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.6 9.6 0 0 1 12 6.8c.85 0 1.7.11 2.5.33 1.9-1.29 2.74-1.02 2.74-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z" />
    </svg>
  );
}

function ChatIcon(): ReactNode {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M4 5h16v11H9l-5 4V5z" />
    </svg>
  );
}

function PeopleIcon(): ReactNode {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="9" cy="8" r="3" />
      <path d="M3 20c0-3 3-4.5 6-4.5s6 1.5 6 4.5M18 8v6m3-3h-6" />
    </svg>
  );
}

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
      <div className={styles.pagehead}>
        <p className={styles.eyebrow}>Getting started</p>
        <h1 className={styles.title}>Let&rsquo;s get your first brief</h1>
        <p className={styles.description}>
          Three quick steps. Connect a source, invite your team if you like, and CAIRN writes your
          first brief. You can always come back to this.
        </p>
      </div>

      <div className={styles.panel}>
        <ConnectRow state={state} />
        <InviteRow workspaceId={workspaceId} />
        <BriefRow state={state} />
      </div>

      {!state.connected && (
        <EmptyState title="No brief yet">
          Your first brief will appear here once a source is connected. It usually takes a few
          minutes after that.
        </EmptyState>
      )}
    </div>
  );
}

function Row({
  icon,
  title,
  description,
  badge,
  locked = false,
  children,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  badge: string;
  locked?: boolean;
  children?: ReactNode;
}): ReactNode {
  return (
    <div className={styles.row} aria-disabled={locked || undefined}>
      <span className={styles.rowIcon}>{icon}</span>
      <div className={styles.rowBody}>
        <div className={styles.rowHead}>
          <div>
            {/* A real heading, not the design's plain `<p>` — losing the page's
              heading structure would cost a screen-reader user the ability
              to jump between these three steps, for a difference nothing
              sighted would even notice. */}
            <h2 className={styles.rowTitle}>{title}</h2>
            <p className={styles.rowDescription}>{description}</p>
          </div>
          <span className={styles.badge}>{badge}</span>
        </div>
        {children}
      </div>
    </div>
  );
}

/** No OAuth route exists for Slack anywhere in the API — same honest
 * treatment as every other provider button with nothing real behind it yet. */
function SlackButton(): ReactNode {
  const [problem, setProblem] = useState<DescribedError | null>(null);

  return (
    <>
      <Button
        variant="secondary"
        onClick={() => {
          setProblem({ message: "Connecting Slack isn't available yet. GitHub works today." });
        }}
      >
        <ChatIcon /> Connect Slack
      </Button>
      {problem !== null && (
        <p className={styles.rowProblem} role="alert">
          {problem.message}
        </p>
      )}
    </>
  );
}

function ConnectRow({ state }: { state: Onboarding }): ReactNode {
  if (state.connected) {
    return (
      <Row
        icon={<CheckCircleIcon />}
        title="Connect a source"
        description={
          state.accountLogin == null
            ? "Connected. CAIRN is reading from it now."
            : `Connected to ${state.accountLogin}. CAIRN is reading from it now.`
        }
        badge="Done"
      />
    );
  }

  return (
    <Row
      icon={<CircleIcon />}
      title="Connect a source"
      description="CAIRN reads from the tools you already use. Start with one — you can add more later."
      badge="Not started"
    >
      <div className={styles.rowActions}>
        {/* An anchor, not a click handler: this is a navigation to GitHub's
          own consent screen, and an admin wants to inspect the destination
          first. */}
        <Button asChild variant="primary">
          <a href={githubInstallUrl()} rel="noopener">
            <GitHubIcon /> Connect GitHub
          </a>
        </Button>
        <SlackButton />
      </div>
    </Row>
  );
}

function InviteRow({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const emailId = useId();

  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  async function send(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const invitation = await client.invite(workspaceId, { email, role: "member" });
      setSent(invitation.email);
      setEmail("");
    } catch (error: unknown) {
      setProblem(describeError(error, "send that invitation"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Row
      icon={<CircleIcon />}
      title="Invite your team"
      description="Optional. CAIRN works on its own, but a brief reads better when it can see the whole team's work."
      badge="Optional"
    >
      <div className={styles.rowActions}>
        {!open && (
          <Button
            variant="secondary"
            onClick={() => {
              setOpen(true);
            }}
          >
            <PeopleIcon /> Invite people
          </Button>
        )}
      </div>

      {open && (
        <form className={styles.inviteForm} onSubmit={(event) => void send(event)}>
          <label className={utility.visuallyHidden} htmlFor={emailId}>
            Email to invite
          </label>
          <input
            id={emailId}
            className={styles.inviteInput}
            type="email"
            required
            placeholder="teammate@company.com"
            value={email}
            disabled={busy}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
          <Button type="submit" variant="primary" loading={busy}>
            {busy ? "Sending…" : "Send invite"}
          </Button>
        </form>
      )}

      {sent !== null && (
        <p className={styles.rowNote} role="status">
          Invited {sent}. They&rsquo;ll get an email with a link to join.
        </p>
      )}
      {problem !== null && (
        <p className={styles.rowProblem} role="alert">
          {problem.message}
        </p>
      )}
    </Row>
  );
}

function BriefRow({ state }: { state: Onboarding }): ReactNode {
  if (!state.connected) {
    return (
      <Row
        icon={<LockIcon />}
        title="See your first brief"
        description="Unlocks once a source is connected. CAIRN needs something to read before it can write."
        badge="Locked"
        locked
      />
    );
  }

  if (state.factsAvailable > 0) {
    return (
      <Row
        icon={<CheckCircleIcon />}
        title="See your first brief"
        description={`CAIRN has understood ${state.factsAvailable.toLocaleString()} things so far. The rest keeps arriving in the background.`}
        badge="Ready"
      >
        <div className={styles.rowActions}>
          <Button asChild variant="primary">
            <Link href="/">Open your brief</Link>
          </Button>
        </div>
      </Row>
    );
  }

  if (!state.importing) {
    return (
      <Row
        icon={<CircleIcon />}
        title="See your first brief"
        description="CAIRN read your repositories and found no activity in the period it imported. That is a real answer rather than a problem — the brief appears as your team works."
        badge="No activity found"
      />
    );
  }

  // Defaulted, not asserted: the generated type marks every field optional.
  const repositories = state.repositories ?? [];
  const finished = repositories.filter((repository) => repository.finished).length;

  return (
    <Row
      icon={<CircleIcon />}
      title={
        state.accountLogin == null ? "Reading your repositories" : `Reading ${state.accountLogin}`
      }
      description="This usually takes a few minutes. You can leave this page — it keeps going."
      badge="In progress"
    >
      {/* The counters are what stops the screen being empty. */}
      <dl className={styles.counters} aria-live="polite">
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
    </Row>
  );
}
