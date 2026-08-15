"use client";

import { useId, useState, type ReactNode } from "react";

import { useAuth, type WorkRole } from "../auth/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { ROLE_PROFILES } from "../roles.js";
import styles from "./RoleChoice.module.css";

/**
 * "What do you do?", chosen by the person it applies to and never by their
 * employer (md/08 §A.6, md/11 §6). Three invariants: declining is offered as
 * plainly as any answer, each option states its consequence, and the screen says
 * the answer changes only what CAIRN opens on — never what anybody can see.
 */
export function RoleChoice({
  onChosen,
  compact = false,
}: {
  /** Called after a successful save, including when the answer is withdrawn. */
  onChosen?: (role: WorkRole | null) => void;
  /** Settings, where the surrounding page has already introduced the section. */
  compact?: boolean;
}): ReactNode {
  const { activeWorkRole, setWorkRole } = useAuth();
  const groupName = useId();

  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<DescribedError | null>(null);

  async function choose(role: WorkRole | null): Promise<void> {
    setBusy(role ?? "none");
    setProblem(null);
    try {
      await setWorkRole(role);
      onChosen?.(role);
    } catch (error: unknown) {
      setProblem(describeError(error, "save what you do"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={styles.choice}>
      {!compact && (
        <p className={styles.lead}>
          CAIRN opens on whatever is most useful to you. It changes nothing about what you or
          anybody else can see — everyone sees the same things either way.
        </p>
      )}

      {/* Radios in a fieldset, not buttons: one question with one answer is
        what a radio group announces and what arrow keys move through. */}
      <fieldset className={styles.options}>
        <legend className={styles.legend}>What do you do?</legend>

        {ROLE_PROFILES.map((profile) => (
          <Option
            key={profile.value}
            id={`${groupName}-${profile.value}`}
            groupName={groupName}
            value={profile.value}
            label={profile.label}
            detail={profile.detail}
            checked={activeWorkRole === profile.value}
            disabled={busy !== null}
            onChoose={() => {
              void choose(profile.value);
            }}
          />
        ))}

        {/* Withdrawing is the same control as choosing, not a hidden reset. */}
        <Option
          id={`${groupName}-none`}
          groupName={groupName}
          value=""
          label="I would rather not say"
          detail="CAIRN opens on the team brief. Everything else works exactly the same."
          checked={activeWorkRole === null}
          disabled={busy !== null}
          onChoose={() => {
            void choose(null);
          }}
        />
      </fieldset>

      {problem !== null && (
        <p className={styles.problem} role="alert">
          {problem.message}
        </p>
      )}
    </div>
  );
}

/** The label carries the name only; the description is attached with
 * `aria-describedby`, so it is not announced as part of a long name. */
function Option({
  id,
  groupName,
  value,
  label,
  detail,
  checked,
  disabled,
  onChoose,
}: {
  id: string;
  groupName: string;
  value: string;
  label: string;
  detail: string;
  checked: boolean;
  disabled: boolean;
  onChoose: () => void;
}): ReactNode {
  const detailId = `${id}-detail`;

  return (
    <div className={styles.option}>
      <input
        id={id}
        className={styles.radio}
        type="radio"
        name={groupName}
        value={value}
        checked={checked}
        disabled={disabled}
        aria-describedby={detailId}
        onChange={onChoose}
      />
      <div className={styles.optionText}>
        <label className={styles.optionLabel} htmlFor={id}>
          {label}
        </label>
        <span className={styles.optionDetail} id={detailId}>
          {detail}
        </span>
      </div>
    </div>
  );
}
