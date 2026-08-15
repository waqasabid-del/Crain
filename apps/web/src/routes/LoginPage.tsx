"use client";

import { Button } from "@cairn/ui";
import { useEffect, useId, useState, type ReactNode, type SyntheticEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "../auth/context.js";
import { describeError, type DescribedError } from "../errors.js";
import styles from "./LoginPage.module.css";

/** Where the reader came from, if anywhere. Query-string supplied, so validated here. */
function intendedDestination(next: string | null): string {
  if (next === null) return "/";
  // A single leading slash keeps this a same-site path; `//evil.example` is
  // protocol-relative and would make this an open redirect.
  if (!next.startsWith("/") || next.startsWith("//")) return "/";
  return next;
}

export function LoginPage(): ReactNode {
  const { status, logIn } = useAuth();
  const router = useRouter();
  const destination = intendedDestination(useSearchParams().get("next"));

  // In an effect, not during render: `router.replace` mid-render warns and can
  // paint the form for a frame after a successful sign-in.
  useEffect(() => {
    if (status === "authenticated") router.replace(destination);
  }, [status, router, destination]);

  // `useId`, not hardcoded ids: duplicates silently break the label/control
  // association if this card is ever rendered twice on a page.
  const emailId = useId();
  const passwordId = useId();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  async function submit(): Promise<void> {
    setSubmitting(true);
    // Cleared on submit, not on keystroke: typing should not remove a message
    // the reader is still reading.
    setProblem(null);
    try {
      await logIn(email, password);
    } catch (error: unknown) {
      setProblem(describeError(error, "sign you in"));
    } finally {
      setSubmitting(false);
    }
  }

  // Sync wrapper typed on `SyntheticEvent`: satisfies `no-misused-promises` and
  // React 19's deprecation of `FormEvent` without a suppression.
  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submit();
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
            <rect x="4" y="12.5" width="10" height="3" rx="1.2" fill="currentColor" />
            <rect x="5.5" y="7.75" width="7" height="3" rx="1.2" fill="currentColor" />
            <rect x="7" y="3" width="4" height="3" rx="1.2" fill="currentColor" />
          </svg>
          <span className={styles.brandName}>Cairn</span>
        </div>

        <h1 className={styles.title}>Sign in</h1>
        <p className={styles.subtitle}>
          CAIRN records what your team is working on and writes it up in plain English.
        </p>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          {/*
            One form-level message, not per-field: a 401 is deliberately
            indistinguishable between unknown address and wrong password
            (auth.py), so no field may claim it. `role="alert"` announces it.
          */}
          {problem !== null && (
            <p className={styles.problem} role="alert">
              {problem.message}
            </p>
          )}

          <div className={styles.field}>
            <label className={styles.label} htmlFor={emailId}>
              Email address
            </label>
            <input
              className={styles.input}
              id={emailId}
              name="email"
              type="email"
              // The browser's credential manager needs these exact tokens to
              // offer a saved password.
              autoComplete="username"
              required
              disabled={submitting}
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
              }}
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={passwordId}>
              Password
            </label>
            <input
              className={styles.input}
              id={passwordId}
              name="password"
              type="password"
              autoComplete="current-password"
              required
              disabled={submitting}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
          </div>

          <Button className={styles.submit} type="submit" variant="primary" loading={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
