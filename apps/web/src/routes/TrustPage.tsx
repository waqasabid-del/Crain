"use client";

import type { Trust } from "@cairn/api-client";
import Link from "next/link";
import { useCallback, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { EmptyState, ErrorState, LoadingState } from "../components/States.js";
import { useAsync } from "../hooks/useAsync.js";
import styles from "./TrustPage.module.css";

/**
 * The Trust & Privacy Center (md/05 §B.6).
 *
 * **A page in the product, not a policy PDF, and open to everybody** — not an
 * administrator's screen. Two audiences and identical content: the engineer
 * deciding each morning whether this thing is on their side, and the buyer whose
 * AI-governance review increasingly gates the purchase. Writing one version for
 * each is how the two come to disagree.
 *
 * **Every number is read from this workspace.** The retention period, which
 * sources are actually connected, how many people are still waiting to be shown
 * the notification. A trust page that states a retention period the product does
 * not apply is the most damaging sentence CAIRN could publish, because its whole
 * audience is people deciding whether the rest is true — so the figure shown here
 * is the one a sweep enforces by deleting.
 *
 * **Nothing on this page is reassurance.** Every line is either something a
 * reader could check by using the product for an afternoon, or a name they can
 * look up. "We take your privacy seriously" would be the first sentence to cut.
 */
export function TrustPage(): ReactNode {
  const { activeWorkspace } = useAuth();

  if (activeWorkspace === null) {
    return (
      <>
        <PageHeader title="Trust and privacy" />
        <EmptyState title="No workspace yet">
          This account is not a member of a workspace, so there is nothing to describe.
        </EmptyState>
      </>
    );
  }

  return <WorkspaceTrust workspaceId={activeWorkspace.id} />;
}

function WorkspaceTrust({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<Trust> => client.getTrust(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load the trust and privacy page");

  if (state.status === "loading") return <LoadingState label="this page" lines={5} />;
  if (state.status === "failed") {
    return (
      <ErrorState title="This page could not be loaded" error={state.error} onRetry={reload} />
    );
  }

  const trust = state.data;
  const sources = trust.sources ?? [];
  const connected = sources.filter((source) => source.connected);

  return (
    <>
      <PageHeader
        title="Trust and privacy"
        description="What CAIRN reads about you, what it will never do with it, and what you control. Everything here is true of this workspace right now — the numbers are read from it, not written into the page."
      />

      <section className={styles.section} aria-labelledby="reads">
        <h2 className={styles.heading} id="reads">
          What CAIRN reads
        </h2>
        <p className={styles.lead}>
          {connected.length === 0
            ? "Nothing is connected yet, so CAIRN is reading nothing. Every source it could ever read is listed here anyway, so you can decide about them before they are switched on."
            : "Every source CAIRN can read is listed, including the ones this workspace has not connected."}
        </p>

        <ul className={styles.sources}>
          {sources.map((source) => (
            <li key={source.source} className={styles.source}>
              <div className={styles.sourceHeader}>
                <span className={styles.sourceName}>{source.label}</span>
                <span className={source.connected ? styles.on : styles.off}>
                  {source.connected ? "Connected" : "Not connected"}
                </span>
              </div>
              <p className={styles.sourceReads}>{source.reads}</p>
            </li>
          ))}
        </ul>

        <p className={styles.aside}>
          You can switch off any source for yourself, and it applies to what CAIRN has already
          attributed to you as well as to anything new.{" "}
          <Link className={styles.link} href="/welcome">
            Your sources and choices
          </Link>
          .
        </p>
      </section>

      <section className={styles.section} aria-labelledby="never">
        <h2 className={styles.heading} id="never">
          What CAIRN never does
        </h2>
        {/*
          The same list the notification screen shows, from the same place in the
          API. Two hand-maintained lists of promises is one list plus a way for
          the product to start promising different things in different places.
        */}
        <ul className={styles.refusals}>
          {(trust.refusals ?? []).map((refusal) => (
            <li key={refusal}>{refusal}</li>
          ))}
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="how">
        <h2 className={styles.heading} id="how">
          How CAIRN works, in practice
        </h2>
        <dl className={styles.commitments}>
          {(trust.commitments ?? []).map((commitment) => (
            <div className={styles.commitment} key={commitment.title}>
              <dt className={styles.commitmentTitle}>{commitment.title}</dt>
              <dd className={styles.commitmentDetail}>{commitment.detail}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={styles.section} aria-labelledby="data">
        <h2 className={styles.heading} id="data">
          What happens to the data
        </h2>
        <dl className={styles.facts}>
          <dt>Raw activity is kept for</dt>
          <dd>
            {trust.retentionDays} days, then deleted. That is the messages and payloads CAIRN
            received. What it understood from them — the record of what the team did, and the briefs
            written from it — is kept as the team&rsquo;s own history.
          </dd>

          <dt>Stored in</dt>
          <dd>{trust.region}</dd>

          <dt>Worker notification</dt>
          <dd>
            {trust.awaitingNotification === 0
              ? "Everyone in this workspace has been shown what CAIRN reads and how to switch it off."
              : `${String(trust.awaitingNotification)} ${trust.awaitingNotification === 1 ? "person has" : "people have"} not been shown it yet. CAIRN attributes nothing to somebody until they have seen it.`}
          </dd>
        </dl>
      </section>

      <section className={styles.section} aria-labelledby="subprocessors">
        <h2 className={styles.heading} id="subprocessors">
          Who else sees it
        </h2>
        <p className={styles.lead}>
          Every company that processes your activity, named, with what it sees. A general assurance
          about partners is not an answer to this question.
        </p>
        <dl className={styles.commitments}>
          {(trust.subprocessors ?? []).map((item) => (
            <div className={styles.commitment} key={item.title}>
              <dt className={styles.commitmentTitle}>{item.title}</dt>
              <dd className={styles.commitmentDetail}>{item.detail}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
