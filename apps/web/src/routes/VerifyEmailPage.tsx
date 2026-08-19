"use client";

import { ApiError } from "@cairn/api-client";
import { Button } from "@cairn/ui";
import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useTheme } from "../theme/context.js";
import styles from "./SignInCard.module.css";

function BrandMark(): ReactNode {
  return (
    <span className={styles.logoMark}>
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

function ClockIcon(): ReactNode {
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
      <path d="M12 7v5l3 2" />
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
        <h2 className={styles.title}>Verify your email</h2>
        <p className={styles.subtitle}>
          Confirming your address keeps your account yours. This only takes a moment.
        </p>
        {children}
        <p className={styles.alternate}>
          Wrong address?{" "}
          <Link href="/login" className={styles.link}>
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

type ResendState = "idle" | "sending" | "sent" | "needs-login" | "error";

export function VerifyEmailPage(): ReactNode {
  const client = useApiClient();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const [problem, setProblem] = useState<DescribedError | null>(null);
  const [resend, setResend] = useState<ResendState>("idle");

  // One request per token, not one per render: an effect with `token` in its
  // dependency array already guarantees that, but StrictMode's deliberate
  // double-invoke in development does not — this guards the network call
  // itself rather than trusting the effect to run once.
  const requested = useRef(false);

  useEffect(() => {
    if (token === "" || requested.current) return;
    requested.current = true;

    client
      .verifyEmail({ token })
      .then(() => {
        // The three sections below are the approved design's own permanent
        // reference states, not a live status this page switches between —
        // so a real success has nowhere distinct to render *to*. It moves
        // the reader on instead, the same way a real password reset does.
        router.replace("/welcome");
      })
      .catch((error: unknown) => {
        // 409 (unknown/expired/used) has no separate handling: the
        // permanent "Link expired" card below already offers the one
        // recovery action there is, regardless of which of the three
        // applied — see `verify_email`'s own docstring for why they're
        // indistinguishable on purpose. Anything else is a real,
        // unexpected failure worth saying so about.
        if (!(error instanceof ApiError && error.status === 409)) {
          setProblem(describeError(error, "verify your email"));
        }
      });
  }, [client, router, token]);

  async function handleResend(): Promise<void> {
    setResend("sending");
    try {
      await client.resendVerification();
      setResend("sent");
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 401) {
        setResend("needs-login");
      } else {
        setResend("error");
      }
    }
  }

  return (
    <Shell>
      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}

      <p className={styles.cardEyebrow}>Verifying</p>
      <div className={styles.innerCard}>
        <div className={styles.confirmRow}>
          <span className={styles.confirmIconSubtle}>
            <LoadingIcon />
          </span>
          <div>
            <p className={styles.confirmTitle}>Checking your link</p>
            <p className={styles.confirmBody}>Hang tight — this usually finishes in a second.</p>
            <div aria-hidden="true">
              <div className={clsx(styles.skeleton, styles.skeleton80)} />
              <div className={clsx(styles.skeleton, styles.skeleton60)} />
              <div className={clsx(styles.skeleton, styles.skeleton40)} />
            </div>
          </div>
        </div>
      </div>

      <hr className={styles.miniDivider} />
      <p className={styles.cardEyebrow}>Verified</p>
      <div className={styles.innerCard}>
        <div className={styles.confirmRow}>
          <span className={styles.confirmIcon}>
            <SuccessIcon />
          </span>
          <div>
            <p className={styles.confirmTitle}>Email verified</p>
            <p className={styles.confirmBody}>
              Your address is confirmed. You&rsquo;re all set to keep going.
            </p>
            <Button variant="primary" asChild>
              <Link href="/welcome" className={styles.confirmAction}>
                Continue
              </Link>
            </Button>
          </div>
        </div>
      </div>

      <hr className={styles.miniDivider} />
      <p className={styles.cardEyebrow}>Link expired</p>
      <div className={styles.innerCard}>
        <div className={styles.confirmRow}>
          <span className={styles.confirmIconMuted}>
            <ClockIcon />
          </span>
          <div>
            <p className={styles.confirmTitle}>This link has expired</p>
            {resend === "sent" ? (
              <p className={styles.confirmBody} role="status">
                A fresh link is on its way to the same address.
              </p>
            ) : resend === "needs-login" ? (
              <p className={styles.confirmBody}>
                Verification links last 48 hours, and this one didn&rsquo;t check out — it may have
                expired or already been used. Requesting a new one needs you signed in on this
                device;{" "}
                <Link href="/login" className={styles.link}>
                  sign in
                </Link>{" "}
                and ask again from there.
              </p>
            ) : (
              <>
                <p className={styles.confirmBody}>
                  Verification links last 48 hours, and this one didn&rsquo;t check out — it may
                  have expired or already been used. No problem — we&rsquo;ll send a fresh one to
                  the same address.
                </p>
                {resend === "error" && (
                  <p className={styles.fieldError} role="alert">
                    Couldn&rsquo;t send a new link just now. Try again in a moment.
                  </p>
                )}
                <Button
                  className={styles.confirmAction}
                  variant="secondary"
                  loading={resend === "sending"}
                  onClick={() => {
                    void handleResend();
                  }}
                >
                  {resend === "sending" ? "Sending…" : "Send a new link"}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}
