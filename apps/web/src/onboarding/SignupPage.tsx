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
 * Signup. Three fields the reader fills in, one the product fills in for
 * them, against md/11's ten-minute target. The account is signed in on
 * creation — the API does the same deliberately.
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

/**
 * The workspace name nobody is asked for.
 *
 * The approved design signs up a *person*, not a company — but the API still
 * requires a workspace name to create one around them. Named after its new
 * owner rather than left blank; renaming it is a settings action, not a
 * signup one.
 */
export function deriveWorkspaceName(displayName: string, email: string): string {
  const name = displayName.trim();
  if (name !== "") return `${name}'s workspace`;

  const local = email.split("@")[0]?.trim() ?? "";
  return local === "" ? "My workspace" : `${local}'s workspace`;
}

/** The approved design's mark: a stroked glyph inside a filled 26px badge,
 * colours flipped on the dark aside so the badge still reads against it. */
function LogoMark({ inverse = false }: { inverse?: boolean }): ReactNode {
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
 * The provider names shown to the reader, and nothing an endpoint could act on.
 *
 * md/15 §3 specifies Google and GitHub SSO for sign-in, and `OAuthIdentity`
 * (db/auth_models.py) already models a linked provider account — but no route
 * initiates or completes an OAuth flow anywhere in the API. There is nothing
 * real to redirect to yet, so a click says that plainly instead of navigating
 * to a guessed URL or pretending to sign anyone in.
 */
type OAuthProviderName = "Google" | "GitHub";

function oauthUnavailableMessage(provider: OAuthProviderName): DescribedError {
  return {
    message: `Signing up with ${provider} isn't available yet. Create your workspace with your work email below instead.`,
  };
}

export function SignupPage(): ReactNode {
  const client = useApiClient();
  const { status } = useAuth();
  const router = useRouter();

  const nameId = useId();
  const emailId = useId();
  const passwordId = useId();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);
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
      const workspaceName = deriveWorkspaceName(displayName, email);
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

  function handleOAuthClick(provider: OAuthProviderName): void {
    setProblem(oauthUnavailableMessage(provider));
  }

  return (
    <div className={styles.page}>
      {/* Hidden below the split's breakpoint (module CSS), not removed: a
       * narrow viewport has no room for narrative beside the form. */}
      <aside className={styles.aside}>
        <div className={styles.asideBrand}>
          <LogoMark inverse />
          CAIRN
        </div>
        <div>
          <p className={styles.eyebrow}>The team operating system</p>
          <h1 className={styles.asideHeading}>Start with a workspace, not a setup marathon.</h1>
          <p className={styles.asideLead}>
            Create your workspace in a minute. Connect a source when you&rsquo;re ready. Nothing is
            scored, ranked, or used against anyone.
          </p>
        </div>
        <p className={styles.asideFoot}>
          SOC 2 in progress · WCAG 2.1 AA · You control every source
        </p>
      </aside>

      <section className={styles.panel}>
        <div className={styles.card}>
          <div className={styles.brand}>
            <LogoMark />
            CAIRN
          </div>

          <h2 className={styles.title}>Create your workspace</h2>
          <p className={styles.subtitle}>
            A few details and you&rsquo;re in. No credit card needed.
          </p>

          {problem !== null && (
            // `role="alert"`, or a screen reader never mentions the failure. Sits
            // above both the OAuth buttons and the form, since either can raise one.
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
              Sign up with Google
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
              Sign up with GitHub
            </Button>
          </div>

          <div className={styles.divider}>
            <span className={styles.dividerLine} />
            <span className={styles.dividerText}>OR</span>
            <span className={styles.dividerLine} />
          </div>

          <form className={styles.form} onSubmit={handleSubmit} noValidate>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={nameId}>
                Full name
              </label>
              <input
                id={nameId}
                className={styles.input}
                value={displayName}
                onChange={(event) => {
                  setDisplayName(event.target.value);
                }}
                autoComplete="name"
                placeholder="Alex Rivera"
                disabled={submitting}
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
                placeholder="you@company.com"
                required
                disabled={submitting}
              />
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor={passwordId}>
                Password
              </label>
              <div className={styles.passwordGroup}>
                <input
                  id={passwordId}
                  className={styles.input}
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                  }}
                  autoComplete="new-password"
                  placeholder="At least 12 characters"
                  required
                  disabled={submitting}
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
              {/* Stated up front: learning the rule by failing it is the most
                common reason a signup takes two attempts. */}
              <p className={styles.hint}>
                Longer is stronger. Aim for a passphrase you can remember — 12 characters or more.
              </p>
            </div>

            <label className={styles.check}>
              <input
                type="checkbox"
                checked={agreed}
                onChange={(event) => {
                  setAgreed(event.target.checked);
                }}
                disabled={submitting}
              />
              <span className={styles.checkText}>
                I agree to the{" "}
                {/* Coloured like the design's links, but not one: no live
                  Terms/Privacy page exists yet, and a link that 404s is worse
                  than plain text that is honest about not going anywhere. */}
                <span className={styles.linkText}>Terms</span> and{" "}
                <span className={styles.linkText}>Privacy Policy</span>.
              </span>
            </label>

            <Button
              className={styles.submit}
              type="submit"
              variant="primary"
              loading={submitting}
              disabled={!agreed}
            >
              {submitting ? "Creating your workspace…" : "Create workspace"}
            </Button>
          </form>

          <p className={styles.footnote}>
            Signing up creates a new workspace and makes you its Owner.
          </p>

          <p className={styles.alternate}>
            Already have an account?{" "}
            <Link className={styles.link} href="/login">
              Sign in
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
