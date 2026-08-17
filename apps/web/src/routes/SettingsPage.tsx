"use client";

import { Button } from "@cairn/ui";
import Link from "next/link";
import { useId, type ReactNode } from "react";

import { useAuth } from "../auth/context.js";
import { PageHeader } from "../components/PageHeader.js";
import { RoleChoice } from "../components/RoleChoice.js";
import { useTheme } from "../theme/context.js";
import { THEME_LABELS, THEME_PREFERENCES, type ThemePreference } from "../theme/theme.js";
import utility from "../styles/utility.module.css";
import styles from "./SettingsPage.module.css";

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

      <section className={styles.section} aria-labelledby="appearance-heading">
        <h2 className={styles.sectionTitle} id="appearance-heading">
          Appearance
        </h2>
        <p className={styles.sectionBody}>
          CAIRN follows your device by default, and switches with it when your system changes at
          sunset.
        </p>

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
      </section>

      <section className={styles.section} aria-labelledby="role-heading">
        <h2 className={styles.sectionTitle} id="role-heading">
          What CAIRN opens on
        </h2>
        <p className={styles.sectionBody}>
          What you do decides which screen CAIRN opens, and how your own record is introduced. It
          changes nothing about what you or anybody else can see, and you can change or withdraw it
          whenever you like.
        </p>
        <RoleChoice compact />
      </section>

      <section className={styles.section} aria-labelledby="account-heading">
        <h2 className={styles.sectionTitle} id="account-heading">
          Account
        </h2>
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
      </section>

      {/*
        The trust commitments, in the product rather than in a policy PDF.

        md/05 §B.3.4 requires this to be stated in-product, so that employees
        know the commitment exists and can hold their employer to it. A short
        summary here, with the full statement in the Trust Center.
      */}
      <section className={styles.section} aria-labelledby="commitments-heading">
        <h2 className={styles.sectionTitle} id="commitments-heading">
          What CAIRN will not do
        </h2>
        <p className={styles.sectionBody}>
          CAIRN never scores, ranks, or compares people. It does not allocate work or recommend who
          should do what. Everyone sees the same categories of information about everyone, including
          about leadership — there is no management-only view, and no role reveals more about a
          person than that person can see about themselves.
        </p>
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
      </section>
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
