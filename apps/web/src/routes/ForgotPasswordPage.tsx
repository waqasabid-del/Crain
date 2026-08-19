"use client";

import { Button } from "@cairn/ui";
import Link from "next/link";
import { useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { useTheme } from "../theme/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { BrandMark } from "../components/BrandMark.js";
import styles from "./SignInCard.module.css";

function CheckIcon(): ReactNode {
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
      <path d="M4 6h16v12H4z" />
      <path d="m4 7 8 6 8-6" />
    </svg>
  );
}

function LockIcon(): ReactNode {
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
      <rect x="4" y="10" width="16" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

export function ForgotPasswordPage(): ReactNode {
  const client = useApiClient();
  const { status, session } = useAuth();
  const { preference, setPreference } = useTheme();
  const emailId = useId();
  const emailHintId = useId();

  // Signed in: the reset is for *this* account, not an address typed in on
  // the reader's behalf — same reasoning as the locked email on `/invite`.
  // Signed out (the ordinary case — someone who forgot their password
  // usually cannot sign in) keeps the free-text field, since there is no
  // session email to lock to.
  const lockedEmail = status === "authenticated" ? (session?.user.email ?? null) : null;

  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const isDark = preference === "dark";
  function handleThemeToggle(): void {
    setPreference(isDark ? "light" : "dark");
  }

  async function submit(): Promise<void> {
    setSubmitting(true);
    setProblem(null);
    try {
      // The response is identical whether or not the address has an account
      // (api-client/routers/auth.py's own doc comment explains why) — so
      // there is nothing in the body to branch on, and nothing for this
      // screen to reveal either way. The confirmation below is shown
      // unconditionally rather than gated on success, matching the
      // approved design exactly.
      await client.forgotPassword({ email: lockedEmail ?? email });
    } catch (error: unknown) {
      setProblem(describeError(error, "send a reset link"));
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
      <aside className={styles.aside}>
        <div className={styles.asideBrand}>
          <BrandMark inverse />
          CAIRN
        </div>
        <div>
          <p className={styles.eyebrow}>Account recovery</p>
          <h1 className={styles.asideHeading}>Happens to everyone.</h1>
          <p className={styles.asideLead}>
            Tell us the email on your account and we&rsquo;ll send a link to set a new password.
            Nothing changes until you follow it.
          </p>
        </div>
        <p className={styles.asideFoot}>
          SOC 2 in progress · WCAG 2.1 AA · You control every source
        </p>
      </aside>

      <section className={styles.panel}>
        <div className={styles.card}>
          <div className={styles.brand}>
            <span className={styles.brandMark}>
              <BrandMark />
              CAIRN
            </span>
            <Button variant="ghost" size="sm" onClick={handleThemeToggle}>
              {isDark ? "Light" : "Dark"}
            </Button>
          </div>

          <h2 className={styles.title}>Reset your password</h2>
          <p className={styles.subtitle}>Enter your email and we&rsquo;ll send a reset link.</p>

          {problem !== null && (
            <p className={styles.problem} role="alert">
              {problem.message}
            </p>
          )}

          <div className={styles.innerCard}>
            <form className={styles.form} onSubmit={handleSubmit} noValidate>
              <div className={styles.field}>
                <label className={styles.label} htmlFor={emailId}>
                  Email
                </label>
                {lockedEmail !== null ? (
                  <>
                    <div className={styles.passwordGroup}>
                      <input
                        className={styles.input}
                        id={emailId}
                        type="email"
                        value={lockedEmail}
                        readOnly
                        aria-describedby={emailHintId}
                      />
                      <span className={styles.passwordToggle} aria-hidden="true">
                        <LockIcon />
                      </span>
                    </div>
                    <p className={styles.hint} id={emailHintId}>
                      You&rsquo;re signed in as this address, so this is the account it will reset.
                    </p>
                  </>
                ) : (
                  <input
                    className={styles.input}
                    id={emailId}
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    required
                    disabled={submitting}
                    value={email}
                    onChange={(event) => {
                      setEmail(event.target.value);
                    }}
                  />
                )}
              </div>

              <Button
                className={styles.submit}
                type="submit"
                variant="primary"
                loading={submitting}
              >
                {submitting ? "Sending…" : "Send reset link"}
              </Button>
            </form>
          </div>

          <hr className={styles.miniDivider} />
          <p className={styles.cardEyebrow}>After submitting</p>

          <div className={styles.innerCard}>
            <div className={styles.confirmRow}>
              <span className={styles.confirmIcon}>
                <CheckIcon />
              </span>
              <div>
                <p className={styles.confirmTitle}>Check your inbox</p>
                <p className={styles.confirmBody}>
                  If an account exists for that address, a reset link is on its way. The link
                  expires in 30 minutes. If nothing arrives, check your spam folder or try again.
                </p>
              </div>
            </div>
          </div>

          <p className={styles.alternate}>
            Remembered it?{" "}
            <Link href="/login" className={styles.link}>
              Back to sign in
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
