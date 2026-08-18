"use client";

import { Button } from "@cairn/ui";
import Link from "next/link";
import { useId, type ReactNode } from "react";

import { useAuth } from "../auth/context.js";
import { ConnectedIdentities } from "../components/ConnectedIdentities.js";
import { MyMeetingRequests } from "../components/MeetingConsent.js";
import { PageHeader } from "../components/PageHeader.js";
import { RoleChoice } from "../components/RoleChoice.js";
import { Section } from "../components/Section.js";
import { useTheme } from "../theme/context.js";
import { THEME_LABELS, THEME_PREFERENCES, type ThemePreference } from "../theme/theme.js";
import utility from "../styles/utility.module.css";
import styles from "./SettingsPage.module.css";

/**
 * The card treatment every section on this screen shares.
 *
 * Read once because `noUncheckedIndexedAccess` types a CSS module lookup as
 * `string | undefined`, and `exactOptionalPropertyTypes` will not let an
 * explicit `undefined` through an optional prop.
 */
const SECTION = styles.section ?? "";

export function SettingsPage(): ReactNode {
  const { session, activeWorkspace, logOut } = useAuth();
  const { preference, setPreference } = useTheme();
  const groupName = useId();

  return (
    <>
      <PageHeader
        title="Preferences"
        description="How CAIRN looks, which account you are signed in with, and the boundaries CAIRN keeps whatever anyone configures."
        actions={
          <Link className={utility.actionLink} href="/trust">
            Trust Center
          </Link>
        }
      />

      {/*
        `Section` rather than four hand-rolled `<section aria-labelledby="…">`
        blocks. The ids here were written by hand and by convention — the same
        convention another route used, which is how `id="never"` came to exist
        twice on one page and resolve to whichever came first. `Section` mints
        its own with `useId`.
      */}
      <Section
        className={SECTION}
        title="Appearance"
        description="CAIRN follows your device by default, and switches with it when your system changes at sunset."
      >
        <fieldset className={styles.choices}>
          <legend className={styles.legend}>Theme</legend>
          {THEME_PREFERENCES.map((option) => (
            <ThemeChoice
              key={option}
              option={option}
              groupName={groupName}
              selected={preference === option}
              onSelect={setPreference}
            />
          ))}
        </fieldset>
      </Section>

      <Section
        className={SECTION}
        title="What CAIRN opens on"
        description="What you do decides which screen CAIRN opens, and how your own record is introduced. It changes nothing about what you or anybody else can see, and you can change or withdraw it whenever you like."
      >
        <RoleChoice compact />
      </Section>

      {/*
        The reader's own identities, in the personal area rather than in
        Workspace settings. Which accounts are somebody's is their own record to
        hold (md/05 §B.2.3), and putting the controls where an administrator
        works would suggest an administrator has a say in it. Nobody does.
      */}
      {activeWorkspace !== null && (
        <>
          <ConnectedIdentities className={SECTION} workspaceId={activeWorkspace.id} />

          {/*
            The reader's own meeting answers, in the personal area for the same
            reason: a consent an Owner could give is worth nothing (md/03 §3.1),
            so the only place to answer is the one place an administrator has no
            reach into. There is no route by which anybody could answer for
            somebody else, and no screen in Workspace settings that shows how
            anybody answered.
          */}
          <MyMeetingRequests className={SECTION} workspaceId={activeWorkspace.id} />
        </>
      )}

      <Section className={SECTION} title="Account">
        <dl className={styles.identity}>
          <dt>Signed in as</dt>
          <dd>{session?.user.email ?? "—"}</dd>
          <dt>Name</dt>
          <dd>{session?.user.displayName ?? "Not set"}</dd>
          <dt>Workspace</dt>
          <dd>{activeWorkspace?.name ?? "None"}</dd>
        </dl>
        <Button
          variant="secondary"
          onClick={() => {
            void logOut();
          }}
        >
          Sign out
        </Button>
      </Section>

      {/*
        The trust commitments, in the product rather than in a policy PDF.

        md/05 §B.3.4 requires this to be stated in-product, so that employees
        know the commitment exists and can hold their employer to it. A short
        summary here, with the full statement in the Trust Center.
      */}
      <Section
        className={SECTION}
        title="What CAIRN will not do"
        description="CAIRN never scores, ranks, or compares people. It does not allocate work or recommend who should do what. Everyone sees the same categories of information about everyone, including about leadership — there is no management-only view, and no role reveals more about a person than that person can see about themselves."
      >
        <p className={styles.sectionBody}>
          Using CAIRN&rsquo;s output as the basis for an employment, disciplinary, or pay decision
          is prohibited by its terms of service. These are permanent product boundaries, not
          settings.
        </p>
        <p className={styles.sectionBody}>
          <Link className={utility.actionLink} href="/trust">
            Read the full statement in the Trust Center
          </Link>
        </p>
      </Section>
    </>
  );
}

interface ThemeChoiceProps {
  option: ThemePreference;
  groupName: string;
  selected: boolean;
  onSelect: (preference: ThemePreference) => void;
}

function ThemeChoice({ option, groupName, selected, onSelect }: ThemeChoiceProps): ReactNode {
  return (
    // The label wraps the input, so the whole row is the target — no `htmlFor`
    // to keep in sync with an id, and 44px of hit area instead of a 16px circle.
    <label className={styles.choice}>
      <input
        className={styles.radio}
        type="radio"
        name={groupName}
        value={option}
        checked={selected}
        onChange={() => {
          onSelect(option);
        }}
      />
      {THEME_LABELS[option]}
    </label>
  );
}
