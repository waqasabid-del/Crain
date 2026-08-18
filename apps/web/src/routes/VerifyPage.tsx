"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import styles from "./LoginPage.module.css";

/**
 * Redeeming a verification link.
 *
 * **This screen did not exist**, while every verification email ever sent
 * linked to it. Signup and resend both built `{CAIRN_PUBLIC_APP_URL}/verify`,
 * and the path 404'd — so no account could complete verification by the route
 * the product told it to use. Nothing caught it: the API endpoint was tested,
 * the message body was tested, and the console email backend printed the link
 * to a log where nobody ever clicked it.
 *
 * **It redeems on arrival rather than behind a button.** Opening the link is
 * already proof of control of the inbox; a "Confirm" button would add a step
 * that proves nothing and loses the people who do not press it. That makes this
 * a state-changing GET in effect, which is normally wrong — it is right here
 * because the token is single-use, unguessable, and delivered only to the
 * address it proves, so the only party who can trigger it is the one it is for.
 *
 * Redeeming does not sign anyone in. The API returns a session payload, and this
 * screen deliberately does not treat that as authentication: holding a link
 * proves an inbox, not a password.
 */
export function VerifyPage(): ReactNode {
  const client = useApiClient();
  const token = useSearchParams().get("token") ?? "";
  const [state, setState] = useState<"working" | "done" | "failed">("working");

  // Strict Mode mounts effects twice in development, and this one spends a
  // single-use token: the second call would redeem an already-redeemed link and
  // show a confirmed reader an error. The ref makes the request happen once per
  // page load rather than once per mount.
  const attempted = useRef(false);

  useEffect(() => {
    if (token === "" || attempted.current) {
      return;
    }
    attempted.current = true;

    void (async () => {
      try {
        await client.verifyEmail({ token });
        setState("done");
      } catch {
        // Not described in detail on purpose. The API answers unknown, expired,
        // already-used and superseded links with one status, because telling
        // them apart would confirm account state to whoever holds the link.
        setState("failed");
      }
    })();
  }, [client, token]);

  if (token === "") {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1 className={styles.title}>This link is incomplete</h1>
          <p className={styles.subtitle}>
            Verification links carry a token that this one is missing — email clients sometimes
            break long links across lines. Sign in and ask for a new one.
          </p>
          <Link href="/login">Go to sign in</Link>
        </div>
      </div>
    );
  }

  if (state === "working") {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1 className={styles.title}>Confirming your address</h1>
          {/* Announced rather than silent: a reader on a slow connection sees a
              card with nothing happening, and a screen reader hears nothing. */}
          <p className={styles.subtitle} role="status">
            One moment.
          </p>
        </div>
      </div>
    );
  }

  if (state === "failed") {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1 className={styles.title}>That link did not work</h1>
          <p className={styles.subtitle}>
            It may have expired, or already been used. Sign in and ask for a new one — nothing about
            your account has changed.
          </p>
          <Link href="/login">Go to sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Your address is confirmed</h1>
        <p className={styles.subtitle}>
          Thank you. You can close this tab, or carry on where you left off.
        </p>
        <Link href="/">Continue to CAIRN</Link>
      </div>
    </div>
  );
}
