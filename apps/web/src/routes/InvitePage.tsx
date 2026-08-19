"use client";

import type { InvitationPreview } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useTheme } from "../theme/context.js";
import { BrandMark } from "../components/BrandMark.js";
import styles from "./SignInCard.module.css";

/**
 * Redeeming an invitation. The copy is an invitation, not a compliance notice
 * (md/11 §4.1).
 *
 * **Redeeming does not sign anyone in.** Holding the link proves control of an
 * inbox, not knowledge of a password, so issuing a session here would let anyone
 * who intercepted it take over an existing account. The reader signs in instead,
 * and lands on `/welcome` — their own record before the team's.
 *
 * The workspace, inviter and role shown here come from `GET
 * /v1/invitations/preview` — a read-only lookup added alongside this page so
 * the aside can say who is inviting whom, to where, before anyone accepts
 * anything. Nothing before this page existed to answer that.
 */

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

function LoadingIcon(): ReactNode {
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
      <path d="M4 12a8 8 0 1 0 8-8M4 4v4h4" />
    </svg>
  );
}

/** No OAuth route exists anywhere in the API — see LoginPage/SignupPage for
 * the same, already-approved treatment. A click says so honestly. */
type OAuthProviderName = "Google" | "GitHub";

function oauthUnavailableMessage(provider: OAuthProviderName): DescribedError {
  return {
    message: `Accepting with ${provider} isn't available yet. Use the form below instead.`,
  };
}

function roleLabel(role: string): string {
  return role.length === 0 ? role : role.charAt(0).toUpperCase() + role.slice(1);
}

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

/** The centred shell, for the states with no workspace to show yet:
 * loading, a missing token, or an invitation that no longer checks out. */
function SimpleShell({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className={styles.singlePage}>
      <div className={styles.card}>
        <Brand />
        {children}
      </div>
    </div>
  );
}

export function InvitePage(): ReactNode {
  const client = useApiClient();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const emailId = useId();
  const emailHintId = useId();
  const nameId = useId();
  const passwordId = useId();

  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [previewProblem, setPreviewProblem] = useState<DescribedError | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(token !== "");

  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const requested = useRef(false);

  useEffect(() => {
    if (token === "" || requested.current) return;
    requested.current = true;

    client
      .previewInvitation(token)
      .then((result) => {
        setPreview(result);
      })
      .catch((error: unknown) => {
        setPreviewProblem(describeError(error, "open this invitation"));
      })
      .finally(() => {
        setLoadingPreview(false);
      });
  }, [client, token]);

  function handleOAuthClick(provider: OAuthProviderName): void {
    setProblem(oauthUnavailableMessage(provider));
  }

  async function submit(): Promise<void> {
    if (preview === null) return;
    setSubmitting(true);
    setProblem(null);
    try {
      await client.acceptInvitation({
        token,
        email: preview.email,
        // Omitted, not sent empty: the API takes a password only for somebody
        // who has no account yet.
        ...(password === "" ? {} : { password }),
        ...(displayName === "" ? {} : { displayName }),
      });
      router.replace(`/login?next=${encodeURIComponent("/welcome")}`);
    } catch (error: unknown) {
      setProblem(describeError(error, "accept your invitation"));
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submit();
  }

  if (token === "") {
    return (
      <SimpleShell>
        <h2 className={styles.title}>This link is incomplete</h2>
        <p className={styles.subtitle}>
          Invitation links carry a token that this one is missing — the link may have been broken by
          an email client. Ask whoever invited you to send it again.
        </p>
        <p className={styles.alternate}>
          <Link href="/login" className={styles.link}>
            Back to sign in
          </Link>
        </p>
      </SimpleShell>
    );
  }

  if (loadingPreview) {
    return (
      <SimpleShell>
        <div className={styles.innerCard}>
          <div className={styles.confirmRow}>
            <span className={styles.confirmIconSubtle}>
              <LoadingIcon />
            </span>
            <div>
              <p className={styles.confirmTitle} role="status">
                Opening your invitation
              </p>
              <p className={styles.confirmBody}>Hang tight — this usually finishes in a second.</p>
            </div>
          </div>
        </div>
      </SimpleShell>
    );
  }

  if (preview === null) {
    return (
      <SimpleShell>
        <h2 className={styles.title}>This invitation can&rsquo;t be used</h2>
        <p className={styles.subtitle}>
          {previewProblem?.message ??
            "This invitation is unknown, has expired, or has already been used."}
        </p>
        <p className={styles.alternate}>
          <Link href="/login" className={styles.link}>
            Back to sign in
          </Link>
        </p>
      </SimpleShell>
    );
  }

  return (
    <div className={styles.page}>
      <aside className={styles.aside}>
        <div className={styles.asideBrand}>
          <BrandMark inverse />
          CAIRN
        </div>
        <div>
          <p className={styles.eyebrow}>You&rsquo;ve been invited</p>
          <h1 className={styles.asideHeading}>
            You&rsquo;ve been invited to {preview.workspaceName}
          </h1>
          <p className={styles.asideLead}>
            {preview.invitedByName} invited you as a {roleLabel(preview.role)}. Accept below and
            CAIRN will keep the team&rsquo;s picture up to date — nothing is scored, ranked, or used
            against anyone.
          </p>
        </div>
        <p className={styles.asideFoot}>
          SOC 2 in progress · WCAG 2.1 AA · You control every source
        </p>
      </aside>

      <section className={styles.panel}>
        <div className={styles.card}>
          <Brand />

          <h2 className={styles.title}>Accept your invitation</h2>
          <p className={styles.subtitle}>
            Set up your access to the {preview.workspaceName} workspace.
          </p>

          {problem !== null && (
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
              Accept with Google
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
              Accept with GitHub
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
                Your email
              </label>
              <div className={styles.passwordGroup}>
                <input
                  id={emailId}
                  className={styles.input}
                  type="email"
                  value={preview.email}
                  readOnly
                  aria-describedby={emailHintId}
                />
                <span className={styles.passwordToggle} aria-hidden="true">
                  <LockIcon />
                </span>
              </div>
              <p className={styles.hint} id={emailHintId}>
                This invitation is tied to this address.
              </p>
            </div>

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
                placeholder="Alex Rivera"
                disabled={submitting}
              />
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor={passwordId}>
                Choose a password
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
              <p className={styles.hint}>
                At least 12 characters. Leave this empty if you already have a CAIRN account.
              </p>
            </div>

            <Button className={styles.submit} type="submit" variant="primary" loading={submitting}>
              {submitting ? "Joining…" : "Accept invitation"}
            </Button>
          </form>

          <p className={styles.footnote}>After accepting you&rsquo;ll sign in.</p>
        </div>
      </section>
    </div>
  );
}
