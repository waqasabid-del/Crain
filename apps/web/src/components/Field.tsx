import clsx from "clsx";
import { useId, type InputHTMLAttributes, type ReactNode } from "react";

import styles from "./Field.module.css";

/** The wiring is owned by the component, so a caller cannot half-do it. */
type OwnedByField = "id" | "aria-describedby" | "aria-invalid" | "className";

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, OwnedByField> {
  label: string;
  /** A requirement, stated up front — "At least 12 characters." Associated with
   * the control, not merely placed beside it. */
  hint?: string;
  /** Present means the field is in error. Drives `aria-invalid`, the message,
   * and the visual state together, so the three cannot drift apart. */
  error?: string;
  /** On the wrapper. `inputClassName` is the escape hatch for the control. */
  className?: string;
  inputClassName?: string;
}

/**
 * A labelled text input, with its hint and its error actually attached to it.
 *
 * The `label`/`htmlFor` pairing was already right everywhere in the app. The
 * three things that were missing everywhere are here:
 *
 * - `aria-invalid`, so a screen reader announces the field as in error rather
 *   than reading a normal-sounding field the reader has just been sent back to;
 * - `aria-describedby` to the *error*, so the reason is heard on focus and not
 *   only by whoever noticed a paragraph appear (WCAG 3.3.1);
 * - `aria-describedby` to the *hint*, so a rule like "at least 12 characters" is
 *   heard before it is broken rather than after (WCAG 3.3.2, 3.3.3).
 *
 * `useId` rather than caller-supplied ids: duplicates break the label/control
 * association silently, and a form rendered twice on one page — a card and a
 * modal — is how that happens without anyone writing a duplicate on purpose.
 */
export function Field({
  label,
  hint,
  error,
  className,
  inputClassName,
  ...input
}: FieldProps): ReactNode {
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  // Error first: a description is read in the order the ids are listed, and what
  // is wrong now matters more than what was required in general.
  const describedBy = [error === undefined ? "" : errorId, hint === undefined ? "" : hintId]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={clsx(styles.field, className)}>
      <label className={styles.label} htmlFor={inputId}>
        {label}
      </label>
      {hint !== undefined && (
        <p className={styles.hint} id={hintId}>
          {hint}
        </p>
      )}
      <input
        {...input}
        id={inputId}
        className={clsx(styles.input, error !== undefined && styles.invalid, inputClassName)}
        aria-invalid={error === undefined ? undefined : true}
        aria-describedby={describedBy === "" ? undefined : describedBy}
      />
      {error !== undefined && (
        // `role="alert"` as well as the description: the description is heard on
        // focus, which does not help a reader whose focus is still on the submit
        // button they just pressed.
        <p className={styles.error} id={errorId} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
