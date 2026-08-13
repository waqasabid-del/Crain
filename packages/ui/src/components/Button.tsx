import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /**
   * Renders a busy state and disables interaction.
   *
   * Uses `aria-busy` plus `disabled` rather than swapping the label for a
   * spinner, so screen reader users are told the control is working instead of
   * hearing its name disappear.
   */
  loading?: boolean;
  children: ReactNode;
}

/**
 * Button.
 *
 * Three variants only. A larger set invites inconsistent use, and in a
 * monochrome system the meaningful distinction is emphasis, not colour.
 *
 * Note there is no `danger` variant. Destructive actions are distinguished by
 * confirmation flow and wording, not by making a button red — consistent with
 * a palette that carries no semantic colour (md/05 §A.4).
 */
export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps): React.JSX.Element {
  return (
    <button
      // Defaulting to "button" prevents the classic bug where a button inside a
      // form submits it unintentionally.
      type={type}
      className={clsx(styles.button, styles[variant], styles[size], className)}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {children}
    </button>
  );
}
