/**
 * One date formatter per intent.
 *
 * There were four `formatDate`s with four different option sets, so the same
 * timestamp read four ways depending on which screen it landed on. Naming the
 * *intent* rather than the shape is what stops a fifth appearing: there is no
 * `formatDate` to reach for, only a question about what the date is for.
 *
 * `undefined` as the locale everywhere, never a hardcoded one: 03/04 means two
 * different days depending on where it is read, and the reader's own locale is
 * the only one that is correct for them.
 *
 * Not a component; it lives here only because `src/components/` is the directory
 * this work owns. It belongs in `src/format/` once that move is co-ordinated.
 */

/** An em dash, not "Invalid Date" and not an empty cell. A missing date is a
 * fact about the record, and it should look deliberate. */
const MISSING = "—";

function parse(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * A day, with no time of day — "4 Jan 2026".
 *
 * For things where the hour is noise: when somebody joined, when a notice was
 * shown. Use this in a `<time dateTime={iso}>` so the machine-readable value
 * survives alongside the localised text.
 */
export function formatDay(iso: string, fallback: string = MISSING): string {
  const date = parse(iso);
  return date === null ? fallback : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

/**
 * A day and a time — "4 Jan 2026, 09:00".
 *
 * For anything auditable, where "which day" is not a precise enough answer:
 * support access, decisions, revocations.
 */
export function formatDayAndTime(iso: string, fallback: string = MISSING): string {
  const date = parse(iso);
  return date === null
    ? fallback
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * When a brief was written — "Written 4 Jan 2026, 09:00".
 *
 * Carries its own verb because it is metadata under a heading rather than a
 * cell, and a bare timestamp there reads as the date the brief is *about*.
 * Falls back to empty: a brief with no legible generation time should show
 * nothing rather than a dash under its title.
 */
export function formatGeneratedAt(iso: string, fallback = ""): string {
  const written = formatDayAndTime(iso, "");
  return written === "" ? fallback : `Written ${written}`;
}
