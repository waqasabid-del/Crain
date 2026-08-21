import type { ProjectSummary } from "@cairn/api-client";
import Link from "next/link";
import type { ReactNode } from "react";

import { headingTag } from "./headings.js";
import { StateBadge } from "./StateBadge.js";
import styles from "./ProjectTile.module.css";

export interface ProjectTileProps {
  project: ProjectSummary;
  /** Where the project's name sits under the page's `<h1>`. Default 3, because
   * a tile normally lives inside a titled `Card` that already owns an `<h2>`. */
  headingLevel?: 2 | 3 | undefined;
}

/**
 * Split a raw project name into the part people read and the part they match.
 *
 * Names arrive here as source strings — "acme-inc/gateway", "waqasabid-del/Crain"
 * — because that is what the connector saw. The last segment is what a person
 * calls the project, but the full string is what appears in a citation, so it
 * is kept verbatim underneath rather than being prettified away: a reader
 * checking evidence has to be able to match the two by eye.
 */
function splitName(name: string): { title: string; qualifier: string | null } {
  const segments = name.split("/").filter((segment) => segment.length > 0);
  const last = segments[segments.length - 1];
  if (last === undefined || segments.length < 2) {
    return { title: name, qualifier: null };
  }
  return { title: last, qualifier: name };
}

/**
 * One or two letters for the monogram.
 *
 * Taken from the *display* name, so "acme-inc/gateway" reads "GA" rather than
 * "AI" — the tile's mark should agree with the tile's title. Two words give
 * their initials; one word gives its first two letters. Never localised or
 * title-cased: only upper-cased, which is a rendering choice, not a rewrite.
 */
function monogram(title: string): string {
  const words = title.split(/[^A-Za-z0-9]+/u).filter((word) => word.length > 0);
  const first = words[0];
  if (first === undefined) {
    return "?";
  }
  const second = words[1];
  if (second !== undefined) {
    return `${first.slice(0, 1)}${second.slice(0, 1)}`.toUpperCase();
  }
  return first.slice(0, 2).toUpperCase();
}

/** Short, unambiguous, and locale-aware: "4 Mar 2026" reads the same to
 * everyone, where a numeric date does not. An unparseable timestamp is treated
 * as no timestamp rather than rendered as "Invalid Date". */
function shortDate(iso: string): string | null {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * A project, as a tile.
 *
 * The same tile on the Overview and on the portfolio, so a project looks like
 * itself wherever it is met. It carries only what somebody declared — name,
 * state, purpose, when the state was last declared. There is deliberately no
 * count of people, no share of anything and no progress: this product reports
 * what is known about work, and a tile that ranked projects against each other
 * would turn a record into a scoreboard.
 *
 * The heading is the link, not the whole card: a card-wide target swallows
 * anything interactive inside it, and a heading link is what a screen reader
 * lists when the reader asks for the page's links.
 */
export function ProjectTile({ project, headingLevel = 3 }: ProjectTileProps): ReactNode {
  const Heading = headingTag(headingLevel);
  const { title, qualifier } = splitName(project.name);
  const declared =
    project.stateDeclaredAt === undefined || project.stateDeclaredAt === null
      ? null
      : shortDate(project.stateDeclaredAt);
  const archived = project.archivedAt !== undefined && project.archivedAt !== null;
  const purpose = project.purpose ?? null;

  return (
    <div className={styles.tile}>
      <div className={styles.head}>
        {/* Decorative: the name it is derived from sits immediately beside it,
            so announcing the initials would only repeat it badly. */}
        <span className={styles.monogram} aria-hidden="true">
          {monogram(title)}
        </span>
        <div className={styles.headText}>
          <Heading className={styles.title}>
            <Link className={styles.link} href={`/projects/${project.id}`}>
              {title}
            </Link>
          </Heading>
          {qualifier !== null && <p className={styles.qualifier}>{qualifier}</p>}
        </div>
        <div className={styles.state}>
          <StateBadge state={project.state} />
        </div>
      </div>

      {purpose === null ? (
        <p className={styles.noPurpose}>No purpose yet</p>
      ) : (
        <p className={styles.purpose}>{purpose}</p>
      )}

      <p className={styles.meta}>
        <span>{declared === null ? "Not set up yet" : `Updated ${declared}`}</span>
        {archived && <span className={styles.archived}>Archived</span>}
      </p>
    </div>
  );
}
