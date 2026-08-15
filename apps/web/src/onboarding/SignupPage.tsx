"use client";

import { Button } from "@cairn/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { describeError, type DescribedError } from "../errors.js";
import styles from "./SignupPage.module.css";

/**
 * Signup. Four fields, one of them derived, against md/11's ten-minute target.
 * The account is signed in on creation — the API does the same deliberately.
 */

/** Lossy and never shown: the API requires a slug, and a reader who sees
 * "northwind-2" wonders what the number means. The random suffix makes a
 * collision between two companies called "Acme" improbable without a round
 * trip. */
export function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);

  const suffix = Math.random().toString(36).slice(2, 8);
  return base === "" ? `workspace-${suffix}` : `${base}-${suffix}`;
}

export function SignupPage(): ReactNode {
  const client = useApiClient();
  const { status } = useAuth();
  const router = useRouter();

  const nameId = useId();
  const emailId = useId();
  const passwordId = useId();
  const workspaceId = useId();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  // Already signed in: go to onboarding rather than offer a second account.
  useEffect(() => {
    if (status === "authenticated") router.replace("/onboarding");
  }, [status, router]);

  async function submit(): Promise<void> {
    setSubmitting(true);
    setProblem(null);
    try {
      await client.signUp({
        email,
        password,
        workspaceName,
        workspaceSlug: slugify(workspaceName),
        displayName: displayName === "" ? null : displayName,
      });
      // Straight to connecting a source; the account does nothing yet.
      router.replace("/onboarding");
    } catch (error: unknown) {
      setProblem(describeError(error, "create your account"));
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submit();
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Start with CAIRN</h1>
        <p className={styles.subtitle}>
          A record of what your team actually did, with the evidence attached.
        </p>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          {problem !== null && (
            // `role="alert"`, or a screen reader never mentions the failure.
            <p className={styles.problem} role="alert">
              {problem.message}
            </p>
          )}

          <div className={styles.field}>
            <label className={styles.label} htmlFor={nameId}>
              Your name
            </label>
            <input
              id={nameId}
              className={styles.input}
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value);
              }}
              autoComplete="name"
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={emailId}>
              Work email
            </label>
            <input
              id={emailId}
              className={styles.input}
              type="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
              autoComplete="email"
              required
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={passwordId}>
              Password
            </label>
            <input
              id={passwordId}
              className={styles.input}
              type="password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
              autoComplete="new-password"
              required
            />
            {/* Stated up front: learning the rule by failing it is the most
              common reason a signup takes two attempts. */}
            <p className={styles.hint}>At least 12 characters.</p>
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={workspaceId}>
              Company or team name
            </label>
            <input
              id={workspaceId}
              className={styles.input}
              value={workspaceName}
              onChange={(event) => {
                setWorkspaceName(event.target.value);
              }}
              autoComplete="organization"
              required
            />
          </div>

          <Button className={styles.submit} type="submit" variant="primary" loading={submitting}>
            {submitting ? "Creating your workspace…" : "Create workspace"}
          </Button>
        </form>

        <p className={styles.alternate}>
          Already have an account? <Link href="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
