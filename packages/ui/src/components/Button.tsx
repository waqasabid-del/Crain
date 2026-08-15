import clsx from "clsx";
import {
  cloneElement,
  isValidElement,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** `aria-busy` plus `disabled`, not a spinner replacing the label, so the name
   * does not disappear for screen reader users. */
  loading?: boolean;
  /** Renders the child as a link for controls that are really navigations.
   * `loading` and `disabled` are ignored — an anchor cannot be disabled. */
  asChild?: boolean;
  children: ReactNode;
}

/** No `danger` variant: destructive actions are distinguished by confirmation
 * flow and wording, not colour (md/05 §A.4). */
export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  asChild = false,
  type = "button",
  ...rest
}: ButtonProps): React.JSX.Element {
  // Not `disabled ?? loading`: that leaves `loading disabled={false}` clickable
  // while announcing itself busy.
  const isDisabled = disabled === true || loading;
  const classes = clsx(styles.button, styles[variant], styles[size], className);

  if (asChild) {
    if (!isValidElement(children)) {
      // Thrown, not fallen back to `<button>`: that would not be a link.
      throw new Error("Button with `asChild` requires a single element child");
    }
    const child = children as ReactElement<{ className?: string }>;
    return cloneElement(child, {
      className: clsx(classes, child.props.className),
    });
  }

  return (
    <button
      type={type}
      className={classes}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      {...rest}
    >
      {children}
    </button>
  );
}
