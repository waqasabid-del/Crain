"use client";

import { Button } from "@cairn/ui";
import Link from "next/link";
import { useEffect, useId, useState, type ReactNode, type SyntheticEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "../auth/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useTheme } from "../theme/context.js";
import { BrandMark } from "../components/BrandMark.js";
import styles from "./SignInCard.module.css";

/** Where the reader came from, if anywhere. Query-string supplied, so validated here. */
function intendedDestination(next: string | null): string {
  if (next === null) return "/";
  // A single leading slash keeps this a same-site path; `//evil.example` is
  // protocol-relative and would make this an open redirect.
  if (!next.startsWith("/") || next.startsWith("//")) return "/";
  return next;
}

function GoogleIcon(): ReactNode {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M21.35 11.1h-9.17v2.98h5.28c-.23 1.4-1.62 4.1-5.28 4.1-3.18 0-5.78-2.63-5.78-5.87s2.6-5.87 5.78-5.87c1.81 0 3.03.77 3.72 1.43l2.53-2.44C17.09 3.7 14.86 2.7 12.18 2.7 7.03 2.7 2.86 6.87 2.86 12s4.17 9.3 9.32 9.3c5.38 0 8.94-3.78 8.94-9.1 0-.61-.07-1.08-.15-1.1z"
      />
    </svg>
  );
}

function GitHubIcon(): ReactNode {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.6 9.6 0 0 1 12 6.8c.85 0 1.7.11 2.5.33 1.9-1.29 2.74-1.02 2.74-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z" />
    </svg>
  );
}

/**
 * Neither SSO nor password reset has a backend behind it yet — no OAuth
 * route exists anywhere in the API (md/15 §3 specifies it; nothing implements
 * it), and there is no reset-password endpoint or page at all. Both controls
 * are shown, per the approved design, but say so honestly on click rather
 * than navigating to a guessed URL or pretending to do something real.
 */
type OAuthProviderName = "Google" | "GitHub";

function oauthUnavailableMessage(provider: OAuthProviderName): DescribedError {
  return {
    message: `Signing in with ${provider} isn't available yet. Use your email and password below instead.`,
  };
}

export function LoginPage(): ReactNode {
  const { status, logIn } = useAuth();
  const { preference, setPreference } = useTheme();
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
  const [showPassword, setShowPassword] = useState(false);
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
      setProblem(describeError(error, "sign you in", "sign-in"));
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

  function handleOAuthClick(provider: OAuthProviderName): void {
    setProblem(oauthUnavailableMessage(provider));
  }

  // Real, working theme switching — unlike the OAuth/reset controls above,
  // this capability genuinely exists (`ThemeProvider` wraps the whole app).
  // "System" is treated as "not dark" here, same as the reference's own
  // toggle, which only ever sets an explicit light/dark value.
  const isDark = preference === "dark";
  function handleThemeToggle(): void {
    setPreference(isDark ? "light" : "dark");
  }

  return (
    <div className={styles.page}>
      {/* Hidden below the split's breakpoint (module CSS), not removed: a
       * narrow viewport has no room for narrative beside the form. */}
      <aside className={styles.aside}>
        <div className={styles.asideBrand}>
          <BrandMark inverse />
          CAIRN
        </div>
        <div>
          <p className={styles.eyebrow}>The team operating system</p>
          <h1 className={styles.asideHeading}>The picture keeps itself up to date.</h1>
          <p className={styles.asideLead}>
            CAIRN reads the work your team already does and writes it back in plain English. Nobody
            updates a ticket. Nothing is scored, ranked, or used against anyone.
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

          <h2 className={styles.title}>Sign in</h2>
          <p className={styles.subtitle}>Welcome back. Enter your details to continue.</p>

          {problem !== null && (
            // One form-level message, not per-field: a 401 is deliberately
            // indistinguishable between unknown address and wrong password
            // (auth.py), so no field may claim it. `role="alert"` announces it.
            // Sits above the OAuth buttons too, since either can raise one.
            <p className={styles.problem} role="alert">
              {problem.message}
            </p>
          )}

          <div className={styles.oauthGroup}>
            <Button
              type="button"
              variant="secondary"
              disabled={submitting}
              onClick={() => {
                handleOAuthClick("Google");
              }}
            >
              <GoogleIcon />
              Continue with Google
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={submitting}
              onClick={() => {
                handleOAuthClick("GitHub");
              }}
            >
              <GitHubIcon />
              Continue with GitHub
            </Button>
          </div>

          <div className={styles.divider}>
            <span className={styles.dividerLine} />
            <span className={styles.dividerText}>OR</span>
            <span className={styles.dividerLine} />
          </div>

          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={emailId}>
                Work email
              </label>
              <input
                className={styles.input}
                id={emailId}
                name="email"
                type="email"
                // The browser's credential manager needs these exact tokens to
                // offer a saved password.
                autoComplete="username"
                placeholder="you@company.com"
                required
                disabled={submitting}
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                }}
              />
            </div>

            <div className={styles.field}>
              <div className={styles.labelRow}>
                <label className={styles.label} htmlFor={passwordId}>
                  Password
                </label>
                <Link href="/forgot-password" className={styles.forgotButton}>
                  Forgot password?
                </Link>
              </div>
              <div className={styles.passwordGroup}>
                <input
                  className={styles.input}
                  id={passwordId}
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
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
            </div>

            <Button className={styles.submit} type="submit" variant="primary" loading={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          <p className={styles.alternate}>
            New to CAIRN?{" "}
            <Link href="/signup" className={styles.link}>
              Create an account
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
