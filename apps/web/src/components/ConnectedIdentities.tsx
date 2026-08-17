"use client";

import {
  ApiError,
  type AttributionHealth,
  type ExternalIdentity,
  type MyIdentities,
} from "@cairn/api-client";
import { Button } from "@cairn/ui";
import Link from "next/link";
import { useCallback, useId, useState, type ReactNode, type SyntheticEvent } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { useAsync } from "../hooks/useAsync.js";
import utility from "../styles/utility.module.css";
import styles from "./ConnectedIdentities.module.css";
import { formatDay } from "./dates.js";
import { Field } from "./Field.js";
import { InlineProblem } from "./InlineProblem.js";
import { Section } from "./Section.js";
import { EmptyState, ErrorState, LoadingState } from "./States.js";
import { StatusNote } from "./StatusNote.js";

/**
 * Which source accounts CAIRN believes are the reader's, and how it knows.
 *
 * **The provider account id is never rendered.** A Slack `U…`, a Chat `users/…`
 * and a GitHub numeric id are the provider's private handles for a human, and
 * putting one on a screen — or in a `title`, an `aria-label` or a `data-`
 * attribute, which are all just as readable — turns a page about somebody's own
 * record into a directory of identifiers. What a reader actually needs to tell
 * two accounts apart is the provider, the state and the date, and on the rare
 * screen with two accounts of the same provider, four masked characters. So
 * `mask` is the only function in this file that touches the value at all, and it
 * keeps four characters.
 *
 * **The server's `explanation` is rendered, not paraphrased.** How CAIRN knows
 * is the question this screen exists to answer, and a client-side sentence about
 * it is a second author who will eventually describe a looser rule than the one
 * `identities.py` enforces. This file writes the labels; the API writes the
 * claims.
 *
 * **There is no administrative view of anybody's identities here, and there is
 * no route to build one from.** `getMyIdentities` takes no subject; the
 * aggregate below is counts. md/05 §B.3.3 makes a per-person attribution
 * breakdown a product-reclassifying feature, and md/15 §2.3 forbids an
 * administrator seeing more about a member than the member sees.
 */

/** The provider's name as a person would say it. */
const PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  slack: "Slack",
  google_chat: "Google Chat",
};

function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

/**
 * The last four characters, and never more.
 *
 * Used only where the reader has two accounts of the same source and would
 * otherwise be looking at two identical rows. `null` when the value is too short
 * for four characters to be a mask rather than the whole thing — in which case
 * the row carries the date instead, which distinguishes it just as well.
 */
export function mask(providerAccountId: string): string | null {
  const trimmed = providerAccountId.trim();
  return trimmed.length > 4 ? `…${trimmed.slice(-4)}` : null;
}

/** What the state and the verification mean, in words, with no score anywhere. */
function stateLabel(identity: ExternalIdentity): string {
  if (identity.state === "revoked") return "Unlinked — no longer attributed to you";
  if (identity.state === "disputed") return "Not yours — no longer attributed to you";
  return identity.verification === "verified_email_match"
    ? "Verified by matching address"
    : "Confirmed by you";
}

// --------------------------------------------------------------------------
// The reader's own identities
// --------------------------------------------------------------------------

export interface ConnectedIdentitiesProps {
  workspaceId: string;
  /** Applied to the section, so a screen with a card treatment keeps it. */
  className?: string;
}

/**
 * The personal section: the caller's own links, and the two controls over them.
 *
 * Whether a workspace exists is the caller's problem, not this component's —
 * `SettingsPage` decides that, because "no workspace" is a fact about the
 * account rather than about identity.
 */
export function ConnectedIdentities({
  workspaceId,
  className,
}: ConnectedIdentitiesProps): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<MyIdentities> => client.getMyIdentities(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load your connected accounts");
  const [confirmed, setConfirmed] = useState<string | null>(null);

  return (
    <Section
      // Spread rather than passed: `exactOptionalPropertyTypes` is on, so an
      // explicit `undefined` is not the same as an absent prop.
      {...(className === undefined ? {} : { className })}
      title="Connected identities"
      description="The accounts CAIRN believes are yours, and how it came to believe it. Only you can see this list, and only you can change it — no Owner, Admin or member of CAIRN's staff can claim an account for you or take one away."
    >
      {state.status === "loading" && (
        <LoadingState label="your connected accounts" shape="rows" lines={2} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="Your connected accounts could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
        />
      )}

      {state.status === "ready" && (
        <>
          {/*
            The server's own statement of the linking rule. Standing guidance
            rather than a result, so it does not announce itself on every paint.
          */}
          <div className={styles.rule}>
            <StatusNote live={false}>{state.data.notice}</StatusNote>
          </div>

          <IdentityList
            identities={state.data.identities ?? []}
            workspaceId={workspaceId}
            onChanged={reload}
          />

          <Proposals proposals={state.data.proposals ?? []} />

          {confirmed !== null && (
            <div className={styles.rule}>
              <StatusNote>{confirmed}</StatusNote>
            </div>
          )}

          <ConfirmForm
            workspaceId={workspaceId}
            onConfirmed={(message) => {
              setConfirmed(message);
              reload();
            }}
          />
        </>
      )}
    </Section>
  );
}

function IdentityList({
  identities,
  workspaceId,
  onChanged,
}: {
  identities: ExternalIdentity[];
  workspaceId: string;
  onChanged: () => void;
}): ReactNode {
  if (identities.length === 0) {
    return (
      <EmptyState title="Nothing connected yet" headingLevel={3}>
        CAIRN has not linked any source account to you. Nothing is being attributed to you by name —
        work from an account nobody has confirmed stays attributed to that account and to no person,
        which is the honest answer rather than a guess at the nearest match.
      </EmptyState>
    );
  }

  // Only where a source appears twice: two identical-looking rows are the one
  // case a reader cannot resolve without something taken from the account id.
  const seen = new Map<string, number>();
  for (const identity of identities) {
    seen.set(identity.provider, (seen.get(identity.provider) ?? 0) + 1);
  }

  return (
    <ul className={styles.list} aria-label="Your connected accounts">
      {identities.map((identity) => (
        <IdentityRow
          key={identity.id}
          identity={identity}
          workspaceId={workspaceId}
          distinguish={(seen.get(identity.provider) ?? 0) > 1}
          onChanged={onChanged}
        />
      ))}
    </ul>
  );
}

/** Which ending is being confirmed, or `null` when nothing has been asked. */
type Ending = "revoked" | "disputed";

function IdentityRow({
  identity,
  workspaceId,
  distinguish,
  onChanged,
}: {
  identity: ExternalIdentity;
  workspaceId: string;
  distinguish: boolean;
  onChanged: () => void;
}): ReactNode {
  const client = useApiClient();
  const [pending, setPending] = useState<Ending | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  const name = providerLabel(identity.provider);
  const suffix = distinguish ? mask(identity.providerAccountId) : null;
  const active = identity.state === "active";

  async function end(disputed: boolean): Promise<void> {
    setBusy(true);
    setProblem(null);
    try {
      await client.revokeMyIdentity(workspaceId, identity.id, disputed);
      setPending(null);
      onChanged();
    } catch (error: unknown) {
      setProblem(describeError(error, "change that link"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={styles.row}>
      <h3 className={styles.rowTitle}>
        {name}
        {suffix !== null && <span className={styles.suffix}> account ending {suffix}</span>}
      </h3>

      <p className={styles.state}>{stateLabel(identity)}</p>

      {/* The server's prose, verbatim: how CAIRN knows is its claim to make. */}
      <p className={styles.explanation}>{identity.explanation}</p>

      <p className={styles.dates}>
        Linked <time dateTime={identity.linkedAt}>{formatDay(identity.linkedAt)}</time>
        {identity.revokedAt != null && (
          <>
            {" · Ended "}
            <time dateTime={identity.revokedAt}>{formatDay(identity.revokedAt)}</time>
          </>
        )}
      </p>

      {problem !== null && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}

      {active &&
        (pending === null ? (
          <div className={styles.actions}>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setPending("revoked");
              }}
            >
              Unlink this {name} account
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setPending("disputed");
              }}
            >
              This {name} account was never mine
            </Button>
          </div>
        ) : (
          <Confirmation
            provider={name}
            ending={pending}
            busy={busy}
            onConfirm={() => {
              void end(pending === "disputed");
            }}
            onCancel={() => {
              setPending(null);
            }}
          />
        ))}
    </li>
  );
}

/**
 * The second step, which states the consequence rather than asking "are you
 * sure?".
 *
 * **Nothing is deleted, and the wording must not imply otherwise.** Revoking
 * stops attribution; the link, how it was made, when, and every fact the link
 * ever produced along with the evidence those facts cite all survive. A
 * confirmation that hinted at deletion would be promising something the API does
 * not do, and the person would find out by looking for something that is still
 * there.
 *
 * The two endings are distinct on purpose. "Unlink" says the link was right and
 * is now over; "never mine" says the link was wrong, and a person is entitled to
 * have the difference recorded.
 */
function Confirmation({
  provider,
  ending,
  busy,
  onConfirm,
  onCancel,
}: {
  provider: string;
  ending: Ending;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}): ReactNode {
  const headingId = useId();
  const disputed = ending === "disputed";

  return (
    <div className={styles.confirm} role="group" aria-labelledby={headingId}>
      <p className={styles.confirmTitle} id={headingId}>
        {disputed
          ? `Record that this ${provider} account was never yours?`
          : `Unlink this ${provider} account?`}
      </p>
      <p className={styles.confirmBody}>
        CAIRN stops attributing this account to you, from now and for what it has already recorded.
        {disputed
          ? " It also records that the original link was wrong, in those words."
          : " The link itself is kept, marked as ended."}{" "}
        Nothing is deleted: the evidence CAIRN gathered, where each piece came from, and the record
        of how this link was made all stay exactly as they are, so what happened here can still be
        checked.
      </p>
      <div className={styles.actions}>
        <Button size="sm" variant="primary" loading={busy} onClick={onConfirm}>
          {disputed ? "Yes, it was never mine" : "Yes, unlink it"}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}>
          Keep it linked
        </Button>
      </div>
    </div>
  );
}

/**
 * Identifiers CAIRN has attached to the reader and has not confirmed.
 *
 * **The reader's own, and nobody else's** — the API returns only `PROPOSED` rows
 * already attached to the caller's person, and there is deliberately no endpoint
 * anywhere that lists the workspace's unclaimed accounts. A menu of colleagues'
 * accounts beside a "that's me" button is the claim-a-colleague attack served as
 * a feature.
 *
 * Read-only: a proposal carries an address or a handle, and a link is made
 * against a source's own account id, so there is nothing here that could be
 * turned into a one-click confirmation without guessing at the missing half.
 */
function Proposals({ proposals }: { proposals: MyIdentities["proposals"] }): ReactNode {
  const rows = proposals ?? [];
  if (rows.length === 0) return null;

  return (
    <div className={styles.block}>
      <h3 className={styles.blockTitle}>Identifiers CAIRN has attached to you</h3>
      <p className={styles.blockBody}>
        Yours and nobody else&rsquo;s: CAIRN never shows you an identifier belonging to a colleague.
        These are not links on their own — until an account is verified or you confirm it, its work
        is attributed to the account and to no person.
      </p>
      <ul className={styles.identifiers}>
        {rows.map((proposal) => (
          <li key={`${proposal.kind}:${proposal.value}`} className={styles.identifier}>
            <span className={styles.identifierKind}>
              {proposal.kind === "email" ? "Email address" : "GitHub handle"}
            </span>{" "}
            {proposal.value}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Confirming an account CAIRN has not linked, by naming it.
 *
 * The account id is typed by the person who owns it and is never echoed back:
 * the field is cleared on success, and the row that appears is described by
 * provider, state and date like every other. That is the whole reason this is a
 * field rather than a list to pick from — the list would be a directory of the
 * workspace's unclaimed accounts, which is the one thing this feature exists to
 * refuse.
 */
function ConfirmForm({
  workspaceId,
  onConfirmed,
}: {
  workspaceId: string;
  onConfirmed: (message: string) => void;
}): ReactNode {
  const client = useApiClient();
  const providerId = useId();
  const [provider, setProvider] = useState("github");
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  async function submit(event: SyntheticEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const value = account.trim();
    if (value === "") return;

    setBusy(true);
    setProblem(null);
    try {
      const linked = await client.confirmMyIdentity(workspaceId, provider, value);
      setAccount("");
      onConfirmed(
        `That ${providerLabel(linked.provider)} account is now linked to you. Work CAIRN had already recorded from it is attributed to you from now on.`,
      );
    } catch (error: unknown) {
      setProblem(confirmFailure(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.block}>
      <h3 className={styles.blockTitle}>Confirm an account is yours</h3>
      <p className={styles.blockBody}>
        If CAIRN is reading a source account of yours that it has not linked, confirm it here and it
        will be attributed to you. You are the only person who can do this for your accounts.
      </p>
      <form
        className={styles.form}
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <div className={styles.control}>
          <label className={styles.label} htmlFor={providerId}>
            Source
          </label>
          <select
            id={providerId}
            className={styles.select}
            value={provider}
            disabled={busy}
            onChange={(event) => {
              setProvider(event.target.value);
            }}
          >
            <option value="github">GitHub</option>
            <option value="slack">Slack</option>
            <option value="google_chat">Google Chat</option>
          </select>
        </div>

        <Field
          label="Your account ID at that source"
          hint="The source's own ID for your account, which you can copy from your profile there. CAIRN stores it but never displays it back to you or to anybody else."
          value={account}
          disabled={busy}
          autoComplete="off"
          onChange={(event) => {
            setAccount(event.target.value);
          }}
        />

        <Button type="submit" loading={busy} disabled={account.trim() === ""}>
          Confirm this account is mine
        </Button>
      </form>

      {problem !== null && (
        <div className={styles.problem}>
          <InlineProblem error={problem} />
        </div>
      )}
    </div>
  );
}

/**
 * The two refusals this form can earn, answered in their own words.
 *
 * The generic 403 copy — "an Owner or an Admin decides who can" — is false here:
 * nobody can grant this, because it is not a permission. And the 409 names
 * nobody, deliberately, since telling one member which colleague holds an
 * account turns the endpoint into a lookup table from accounts to people.
 */
function confirmFailure(error: unknown): DescribedError {
  if (error instanceof ApiError && error.is("not-your-record")) {
    return {
      message:
        "CAIRN has not recorded any work against your account yet, so there is nothing to attach this to. This becomes available as soon as it has.",
    };
  }
  if (error instanceof ApiError && error.is("identity-already-linked")) {
    return {
      message:
        "Somebody in this workspace has already confirmed that account. CAIRN does not say who. If you believe it is yours, ask them to unlink it first.",
    };
  }
  return describeError(error, "confirm that account");
}

// --------------------------------------------------------------------------
// The workspace aggregate
// --------------------------------------------------------------------------

interface ProviderCounts {
  provider: string;
  resolved: number;
  unresolved: number;
}

/** One row per source that appears on either side of the count. */
export function providerCounts(health: AttributionHealth): ProviderCounts[] {
  const resolved = health.resolvedByProvider ?? {};
  const unresolved = health.unresolvedByProvider ?? {};
  const providers = [...new Set([...Object.keys(resolved), ...Object.keys(unresolved)])].sort();

  return providers.map((provider) => ({
    provider,
    resolved: resolved[provider] ?? 0,
    unresolved: unresolved[provider] ?? 0,
  }));
}

/**
 * Attribution across the workspace, for an Owner or an Admin.
 *
 * **Counts, and nothing that could be about a person.** There is no name here,
 * no row per member, no "most unresolved" list and no measure of anybody's
 * activity — not because they are withheld, but because the response carries
 * none of them. What an administrator can do with this is ask the team to
 * confirm their own accounts, which is the only action that would help anyway.
 *
 * The caller gates this on `administers`. That gate is courtesy: the API refuses
 * a member independently, and nothing here is the only thing standing in front
 * of the request.
 */
export function AttributionHealthSummary({ workspaceId }: { workspaceId: string }): ReactNode {
  const client = useApiClient();
  const load = useCallback(
    (signal: AbortSignal): Promise<AttributionHealth> =>
      client.getAttributionHealth(workspaceId, { signal }),
    [client, workspaceId],
  );
  const { state, reload } = useAsync(load, "load attribution health");

  return (
    <Section
      variant="eyebrow"
      title="Attribution health"
      description="How many source accounts have somebody who has claimed them. Everyone manages their own connected accounts in Preferences — there is nothing to reassign here, and CAIRN will not tell you which of your colleagues is unresolved."
    >
      {state.status === "loading" && (
        <LoadingState label="attribution health" shape="rows" lines={2} />
      )}

      {state.status === "failed" && (
        <ErrorState
          title="Attribution health could not be loaded"
          error={state.error}
          onRetry={reload}
          headingLevel={3}
          action={
            <Link className={utility.actionLink} href="/settings">
              Manage your own connected accounts
            </Link>
          }
        />
      )}

      {state.status === "ready" &&
        (providerCounts(state.data).length === 0 ? (
          <EmptyState title="Nothing to count yet" headingLevel={3}>
            No source account has been linked to anybody in this workspace. Work CAIRN reads is
            still recorded; it is attributed to the account it came from and to no person until
            somebody confirms that account is theirs.
          </EmptyState>
        ) : (
          <>
            <ul className={styles.counts} aria-label="Accounts by source">
              {providerCounts(state.data).map((row) => (
                <li key={row.provider} className={styles.count}>
                  <span className={styles.countName}>{providerLabel(row.provider)}</span>
                  <span className={styles.countValue}>
                    {row.resolved} claimed · {row.unresolved} unclaimed
                  </span>
                </li>
              ))}
            </ul>

            <p className={styles.blockBody}>
              {state.data.revoked} {state.data.revoked === 1 ? "link has" : "links have"} been
              unlinked by the person they belonged to, and {state.data.disputed}{" "}
              {state.data.disputed === 1 ? "was" : "were"} marked as never theirs. Both are
              ordinary: they are how the record gets corrected.
            </p>

            {/* The server's own statement of what this view cannot answer. */}
            <div className={styles.rule}>
              <StatusNote live={false}>{state.data.notice}</StatusNote>
            </div>

            <p className={styles.blockBody}>
              To improve these numbers, ask the team to confirm their own accounts in Preferences.
              Nobody — including you — can confirm an account on somebody else&rsquo;s behalf.
            </p>
          </>
        ))}
    </Section>
  );
}
