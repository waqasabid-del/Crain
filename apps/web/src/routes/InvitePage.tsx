"use client";

import { Button } from "@cairn/ui";
import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import styles from "./LoginPage.module.css";

/**
 * Redeeming an invitation. The copy is an invitation, not a compliance notice
 * (md/11 §4.1).
 *
 * **Redeeming does not sign anyone in.** Holding the link proves control of an
 * inbox, not knowledge of a password, so issuing a session here would let anyone
 * who intercepted it take over an existing account. The reader signs in instead,
 * and lands on `/welcome` — their own record before the team's.
 */
export function InvitePage(): ReactNode {
  const client = useApiClient();
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";

  const emailId = useId();
  const passwordId = useId();
  const nameId = useId();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  async function submit(): Promise<void> {
    setBusy(true);
    setProblem(null);
    try {
      await client.acceptInvitation({
        token,
        email,
        // Omitted, not sent empty: the API takes a password only for somebody
        // who has no account yet.
        ...(password === "" ? {} : { password }),
        ...(displayName === "" ? {} : { displayName }),
      });
      router.replace(`/login?next=${encodeURIComponent("/welcome")}`);
    } catch (error: unknown) {
      setProblem(describeError(error, "accept your invitation"));
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>): void {
    event.preventDefault();
    void submit();
  }

  if (token === "") {
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <h1 className={styles.title}>This link is incomplete</h1>
          <p className={styles.subtitle}>
            Invitation links carry a token that this one is missing. Ask whoever invited you to send
            it again — the link may have been broken by an email client.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>You have been invited to CAIRN</h1>
        {/* What the product does, before what it needs. */}
        <p className={styles.subtitle}>
          CAIRN writes up your team&rsquo;s week from the work you already do. You will see your own
          record first, you can correct anything in it, and you can switch off any source it reads.
        </p>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          {problem !== null && (
            <p className={styles.problem} role="alert">
              {problem.message}
            </p>
          )}

          <div className={styles.field}>
            <label className={styles.label} htmlFor={emailId}>
              The email this invitation was sent to
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
            <label className={styles.label} htmlFor={passwordId}>
              Choose a password
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
            />
            <p className={styles.hint}>
              At least 12 characters. Leave this empty if you already have a CAIRN account.
            </p>
          </div>

          <Button className={styles.submit} type="submit" variant="primary" loading={busy}>
            {busy ? "Joining…" : "Join your team"}
          </Button>
        </form>
      </div>
    </div>
  );
}
