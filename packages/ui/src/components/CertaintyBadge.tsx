import clsx from "clsx";
import { useCallback, useLayoutEffect, useRef, useState } from "react";

import styles from "./CertaintyBadge.module.css";

export type Certainty = "verified" | "observed" | "suggested";

export interface CertaintyBadgeProps {
  certainty: Certainty;
  className?: string;
}

const LABEL: Record<Certainty, string> = {
  verified: "Verified",
  observed: "Observed",
  suggested: "Suggested",
};

const DESCRIPTION: Record<Certainty, string> = {
  verified: "Taken directly from an unambiguous source, such as a merged pull request.",
  observed: "Drawn from clear discussion, or corroborated across more than one source.",
  suggested: "Inferred from a single source such as a meeting transcript. Worth checking.",
};

/** Breathing room between the tooltip and the viewport edge, in px. Matches
 * --space-2; kept as a number because it is arithmetic, not a style. */
const VIEWPORT_GUTTER_PX = 8;

/**
 * Keeps the tooltip inside the viewport.
 *
 * `max-width` alone is not enough: the panel is anchored to the badge's left
 * edge, so a badge two thirds of the way across a 320px screen pushes even a
 * narrow panel off the right. Measuring after paint and translating back by the
 * overflow is the only way to know, short of an anchor-positioning API that is
 * not yet available everywhere. Never shifts further than the panel's own
 * distance from the left edge, so correcting one overflow cannot cause another.
 */
function useViewportClamp(open: boolean): React.RefObject<HTMLSpanElement | null> {
  const ref = useRef<HTMLSpanElement | null>(null);

  useLayoutEffect(() => {
    const panel = ref.current;
    if (!open || panel === null) return;

    panel.style.removeProperty("--tooltip-shift");
    const box = panel.getBoundingClientRect();
    const overflow = box.right - (window.innerWidth - VIEWPORT_GUTTER_PX);
    if (overflow <= 0) return;

    const shift = Math.min(overflow, Math.max(box.left - VIEWPORT_GUTTER_PX, 0));
    panel.style.setProperty("--tooltip-shift", `-${String(Math.round(shift))}px`);
  }, [open]);

  return ref;
}

/**
 * Tiers differ by weight and border, never colour (WCAG 1.4.1, and colour reads
 * as a judgement about the person). No percentages — md/05 §A.2.1.
 *
 * A button rather than a focusable `role="img"`. The description has to be
 * reachable without a pointer (WCAG 1.4.13), and the previous version bought
 * that with `tabIndex={0}` on a non-interactive element: on a page of thirty
 * claims that is thirty tab stops that do nothing when activated. A disclosure
 * button is a stop that earns its place, and it is what assistive technology
 * announces as operable — which the old markup claimed by being focusable and
 * then denied by its role.
 */
export function CertaintyBadge({ certainty, className }: CertaintyBadgeProps): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const panelRef = useViewportClamp(open);

  const dismiss = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    // WCAG 2.2 SC 1.4.13 — content revealed on hover or focus must be
    // dismissible without moving either. Escape does not blur the badge, so the
    // description can be re-opened with Enter without leaving the keyboard.
    if (event.key === "Escape") setOpen(false);
  }, []);

  return (
    <button
      type="button"
      className={clsx(styles.badge, styles[certainty], className)}
      aria-expanded={open}
      aria-label={`${LABEL[certainty]}: ${DESCRIPTION[certainty]}`}
      onClick={() => {
        setOpen((wasOpen) => !wasOpen);
      }}
      onKeyDown={dismiss}
      onFocus={() => {
        setOpen(true);
      }}
      onBlur={() => {
        setOpen(false);
      }}
      onPointerEnter={() => {
        setOpen(true);
      }}
      onPointerLeave={() => {
        setOpen(false);
      }}
    >
      {LABEL[certainty]}
      {/* aria-hidden because the same words are already in the accessible name;
          without it a screen reader announces the description twice. */}
      <span ref={panelRef} className={styles.description} data-open={open} aria-hidden="true">
        {DESCRIPTION[certainty]}
      </span>
    </button>
  );
}
