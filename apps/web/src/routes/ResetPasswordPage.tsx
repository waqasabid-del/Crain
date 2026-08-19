"use client";

import { ApiError } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useTheme } from "../theme/context.js";
import styles from "./SignInCard.module.css";

function BrandMark({ inverse = false }: { inverse?: boolean }): ReactNode {
  return (
    <span className={inverse ? styles.logoMarkInverse : styles.logoMark}>
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M12 3l3 5 6 1-4.5 4 1 6-5.5-3-5.5 3 1-6L3 9l6-1z" />
      </svg>
    </span>
  );
}

function SuccessIcon(): ReactNode {
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
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.5 2.5 4.5-5" />
    </svg>
  );
}

function ErrorIcon(): ReactNode {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={styles.fieldErrorIcon}
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4m0 4h.01" />
    </svg>
  );
}

/** Brand row + theme toggle, identical on every state this page can be in. */
function Brand(): ReactNode {
  const { preference, setPreference } = useTheme();
  const isDark = preference === "dark";
  return (
    <div className={styles.brand}>
      <span className={styles.brandMark}>
        <BrandMark />
        CAIRN
      </span>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          setPreference(isDark ? "light" : "dark");
        }}
      >
        {isDark ? "Light" : "Dark"}
      </Button>
    </div>
  );
}

function Shell({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className={styles.singlePage}>
      <div className={styles.card}>
        <Brand />
        {children}
      </div>
    </div>
  );
}

export function ResetPasswordPage(): ReactNode {
  const client = useApiClient();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const passwordId = useId();
  const confirmId = useId();

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);
  // Set only for a 409 — an unknown, expired or already-used link. Distinct
  // from `problem`: retrying the same token can never succeed, so this
  // replaces the form entirely rather than sitting above it.
  const [tokenInvalid, setTokenInvalid] = useState(false);

  const confirmTouched = confirmPassword !== "";
  const passwordsMatch = password === confirmPassword;

  if (token === "") {
    return (
      <Shell>
        <h2 className={styles.title}>This link is incomplete</h2>
        <p className={styles.subtitle}>
          Password reset links carry a token that this one is missing. Request a new one, or ask
          whoever sent it to send it again — the link may have been broken by an email client.
        </p>
        <p className={styles.alternate}>
          <Link href="/forgot-password" className={styles.link}>
            Request a new link
          </Link>
        </p>
      </Shell>
    );
  }

  async function submit(): Promise<void> {
    setSubmitting(true);
    setProblem(null);
    try {
      await client.resetPassword({ token, password });
      // No separate success screen: the "Success state" card below is a
      // permanent, captioned illustration (per the approved design), not
      // something gated on this request — showing a second, real one here
      // would just duplicate it. Sign-in is the actual next step, so this
      // goes straight there.
      router.replace("/login");
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setTokenInvalid(true);
      } else {
        setProblem(describeError(error, "reset your password"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!passwordsMatch) return;
    void submit();
  }

  if (tokenInvalid) {
    return (
      <Shell>
        <h2 className={styles.title}>This link is no longer valid</h2>
        <p className={styles.subtitle}>
          It may have already been used, or it may have expired — reset links last 30 minutes.
          Request a fresh one to continue.
        </p>
        <Button
          className={styles.submit}
          variant="primary"
          onClick={() => {
            router.replace("/forgot-password");
          }}
        >
          Request a new link
        </Button>
        <p className={styles.alternate}>
          <Link href="/login" className={styles.link}>
            Back to sign in
          </Link>
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <h2 className={styles.title}>Set a new password</h2>
      <p className={styles.subtitle}>Choose a password you haven&rsquo;t used here before.</p>

      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}

      <div className={styles.innerCard}>
        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor={passwordId}>
              New password
            </label>
            <div className={styles.passwordGroup}>
              <input
                className={styles.input}
                id={passwordId}
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                placeholder="At least 12 characters"
                required
                disabled={submitting}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
              />
              <button
                type="button"
                className={styles.passwordToggle}
                onClick={() => {
                  setShowPassword((current) => !current);
                }}
                aria-label={showPassword ? "Hide password" : "Show password"}
                disabled={submitting}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
            <p className={styles.hint}>
              Longer is stronger. A passphrase of a few words works well.
            </p>
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={confirmId}>
              Confirm password
            </label>
            <input
              className={clsx(styles.input, confirmTouched && !passwordsMatch && styles.inputError)}
              id={confirmId}
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              placeholder="Re-enter your password"
              required
              disabled={submitting}
              value={confirmPassword}
              onChange={(event) => {
                setConfirmPassword(event.target.value);
              }}
              aria-invalid={confirmTouched && !passwordsMatch}
            />
            {confirmTouched &&
              (passwordsMatch ? (
                <p className={styles.fieldOk}>Passwords match.</p>
              ) : (
                <p className={styles.fieldError}>
                  <ErrorIcon /> Those don&rsquo;t match yet. Re-enter the same password in both
                  fields.
                </p>
              ))}
          </div>

          <Button
            className={styles.submit}
            type="submit"
            variant="primary"
            loading={submitting}
            disabled={!confirmTouched || !passwordsMatch}
          >
            {submitting ? "Updating…" : "Update password"}
          </Button>
        </form>

        {/* A fixed illustration, not driven by the fields above — the
          approved design captions it "Mismatch example" precisely because
          it's a reference for what the error looks like, not a live report
          on what the reader just typed. */}
        <div className={styles.cardFoot}>
          <p className={styles.exampleCaption}>Mismatch example</p>
          <input
            className={styles.input}
            type="password"
            value="differentvalue"
            aria-label="Password example that does not match"
            readOnly
          />
          <p className={styles.fieldError}>
            <ErrorIcon /> Those don&rsquo;t match yet. Re-enter the same password in both fields.
          </p>
        </div>
      </div>

      <hr className={styles.miniDivider} />
      <p className={styles.cardEyebrow}>Success state</p>

      <div className={styles.innerCard}>
        <div className={styles.confirmRow}>
          <span className={styles.confirmIcon}>
            <SuccessIcon />
          </span>
          <div>
            <p className={styles.confirmTitle}>Password updated</p>
            <p className={styles.confirmBody}>
              Your password has been changed. To keep your account safe, all other sessions were
              signed out — you&rsquo;ll need to sign in again on other devices.
            </p>
            <Button variant="primary" asChild>
              <Link href="/login" className={styles.confirmAction}>
                Continue to sign in
              </Link>
            </Button>
          </div>
        </div>
      </div>

      <p className={styles.alternate}>
        <Link href="/login" className={styles.link}>
          Back to sign in
        </Link>
      </p>
    </Shell>
  );
}
