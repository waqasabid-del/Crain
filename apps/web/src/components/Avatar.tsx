import type { ReactNode } from "react";

import styles from "./Avatar.module.css";

export interface AvatarProps {
  name: string;
  /** sm beside dense text, md in a list row. Default md. */
  size?: "sm" | "md" | undefined;
}

/**
 * A person's initials in a circle, and nothing more.
 *
 * No photograph and **no colour derived from the name**: a per-person hue is a
 * per-person signal, and once people can be told apart at a glance by tint the
 * page has started sorting them. Every monogram here is the same ink on the
 * same ground, so the avatar locates a row without characterising whoever is in
 * it.
 *
 * `aria-hidden` always. The name is rendered as text beside every avatar, so an
 * announcing monogram would read each colleague's name twice.
 */
export function Avatar({ name, size = "md" }: AvatarProps): ReactNode {
  return (
    <span className={size === "sm" ? styles.sm : styles.md} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

/**
 * First letter of the first word, plus the first letter of the last — the
 * convention people already read as "initials". One word gives one letter
 * rather than two from the same word, which looks like a typo.
 *
 * A name we cannot take a letter from falls back to a dash, not a "?": an
 * unknown name is missing data, not a question put to the reader.
 */
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "—";

  const first = words[0] ?? "";
  const last = words[words.length - 1] ?? "";
  const letters = words.length === 1 ? first.slice(0, 1) : first.slice(0, 1) + last.slice(0, 1);

  return letters.toUpperCase() || "—";
}
