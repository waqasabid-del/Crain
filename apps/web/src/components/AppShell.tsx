"use client";

import { Button } from "@cairn/ui";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "../auth/context.js";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher.js";
import styles from "./AppShell.module.css";

interface Destination {
  readonly href: string;
  readonly label: string;
  /** Only the overview: without it "/" prefix-matches every path and two links
   * claim `aria-current="page"` at once. */
  readonly exact: boolean;
  /** Decides what to *offer*, never what to allow — the API enforces. A hidden
   * link is a courtesy, not a control. */
  readonly admin: boolean;
  /** Key into `NAV_ICONS`. A destination whose key is missing renders its
   * label alone rather than a gap - the icon is redundant with the label by
   * design, so its absence costs nothing. */
  readonly icon: string;
}

interface NavGroup {
  readonly key: string;
  readonly label: string;
  readonly items: readonly Destination[];
}

/**
 * The destinations that exist today (md/15 §4.1), grouped by what the reader is
 * there to do rather than by which team built them.
 *
 * The three headings are md/15 §1's three surfaces, in its own words:
 * *Workspace* is the customer application, *Administration* is tenant
 * administration (md/15 §4.2), and *Trust & privacy* is the permanent, visible
 * centre md/05 §B.6 requires for everybody — given its own heading precisely so
 * it never reads as one more setting inside Administration.
 *
 * Every href is unchanged from the flat list this replaces. The labels are the
 * screen names md/15 §4 uses — "Daily brief" for the daily narrative (§4.1 #7),
 * "Archive" for the brief archive (#8), "Activity" for the team feed (#11),
 * "Workspace settings" for workspace overview and configuration (§4.2 #17–21).
 * "Your record" is deliberately second person: md/05 §B.2 makes the record the
 * person's own, and "My week" states a period where the commitment is about
 * ownership.
 */
const NAV_GROUPS: readonly NavGroup[] = [
  {
    key: "workspace",
    label: "Workspace",
    items: [
      { href: "/", label: "Dashboard", exact: true, admin: false, icon: "overview" },
      { href: "/brief", label: "Daily brief", exact: false, admin: false, icon: "brief" },
      { href: "/feed", label: "Activity", exact: false, admin: false, icon: "activity" },
      { href: "/projects", label: "Projects", exact: false, admin: false, icon: "projects" },
      { href: "/people", label: "Team", exact: false, admin: false, icon: "team" },
      { href: "/me", label: "Your record", exact: false, admin: false, icon: "record" },
      { href: "/archive", label: "Archive", exact: false, admin: false, icon: "archive" },
    ],
  },
  {
    key: "management",
    label: "Administration",
    items: [
      {
        href: "/admin",
        label: "Workspace settings",
        exact: false,
        admin: true,
        icon: "settings",
      },
      { href: "/settings", label: "Preferences", exact: false, admin: false, icon: "preferences" },
    ],
  },
  {
    key: "trust",
    label: "Trust & privacy",
    items: [{ href: "/trust", label: "Trust Center", exact: false, admin: false, icon: "trust" }],
  },
];

/**
 * One line-drawing per destination, on a 24-unit grid, stroked in
 * `currentColor` so each follows its row's own colour and state for free.
 *
 * `aria-hidden`, always: the label beside it is the accessible name, and an
 * icon that also announced itself would double every destination in a screen
 * reader's list.
 */
const NAV_ICONS: Readonly<Record<string, string>> = {
  overview: "M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-4H4zM14 8h6V4h-6z",
  brief: "M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h7",
  projects: "M4 7h5l2 2h9v10H4zM4 7V5h5l2 2",
  activity: "M4 12h3l2.5-6 3 12 2.5-6h5",
  team: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M3 20a6 6 0 0 1 12 0M17 11a3 3 0 1 0 0-6M21 20a6 6 0 0 0-4-5.6",
  record: "M7 3h10v18l-5-3-5 3zM10 8h4",
  archive: "M3 7h18v4H3zM5 11v9h14v-9M10 15h4",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.2 3H9.8l-.4 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.7h4.4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5A7 7 0 0 0 19 12",
  preferences: "M4 6h16M4 12h16M4 18h16M9 4v4M15 10v4M7 16v4",
  trust: "M12 3l7 3v6c0 4.4-3 8-7 9-4-1-7-4.6-7-9V6z",
};

function NavIcon({ name }: { name: string }): ReactNode {
  const path = NAV_ICONS[name];
  if (path === undefined) return null;
  return (
    <svg
      className={styles.navIcon}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={path} />
    </svg>
  );
}

/** Tenant roles as md/15 §2.2 names them. A lookup rather than a capitalisation
 * helper: the label is copy, and copy is not derived from an identifier. */
const ROLE_LABEL: Readonly<Record<string, string>> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  viewer: "Viewer",
};

function isCurrent(pathname: string, destination: Destination): boolean {
  return destination.exact
    ? pathname === destination.href
    : pathname === destination.href || pathname.startsWith(`${destination.href}/`);
}

/** Everything inside the panel that can hold focus, in document order. */
const FOCUSABLE =
  'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** `aria-hidden`: the wordmark beside it already carries the name. */
function CairnMark(): ReactNode {
  return (
    <svg
      className={styles.brandMark}
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="4" y="12.5" width="10" height="3" rx="1.2" fill="currentColor" />
      <rect x="5.5" y="7.75" width="7" height="3" rx="1.2" fill="currentColor" />
      <rect x="7" y="3" width="4" height="3" rx="1.2" fill="currentColor" />
    </svg>
  );
}

/** Two glyphs, one box, so the button does not change width as it toggles. */
function MenuMark({ open }: { open: boolean }): ReactNode {
  return (
    <svg
      className={styles.menuMark}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
    >
      {open ? (
        <path
          d="M3.5 3.5 L12.5 12.5 M12.5 3.5 L3.5 12.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      ) : (
        <path
          d="M2.5 4.5 H13.5 M2.5 8 H13.5 M2.5 11.5 H13.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}

export function AppShell({ children }: { children: ReactNode }): ReactNode {
  const { session, logOut, activeRole } = useAuth();
  const pathname = usePathname();

  const panelId = useId();
  const headingId = useId();
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstLinkRef = useRef<HTMLAnchorElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  const isManager = activeRole === "owner" || activeRole === "admin";
  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((destination) => !destination.admin || isManager),
    // A group whose only item is role-gated must disappear with it: a heading
    // over an empty list is announced as a section that contains nothing.
  })).filter((group) => group.items.length > 0);

  const user = session?.user ?? null;
  const displayName = user?.displayName ?? null;
  const email = user?.email ?? null;
  const roleLabel = activeRole === null ? null : (ROLE_LABEL[activeRole] ?? null);

  /** The link that receives focus when the panel opens. Read from the data
   * rather than counted during render, so it stays the first link when a group
   * is filtered away. */
  const firstHref = groups[0]?.items[0]?.href ?? null;

  /*
   * Closing always returns focus to the trigger. The panel is `display: none`
   * once closed, so whatever was focused inside it is removed from the document
   * and focus falls to `<body>` — the reader would be tabbing from the top of
   * the page again with no idea why.
   */
  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    triggerRef.current?.focus();
  }, []);

  // Arriving somewhere new collapses the panel: it sits above the content the
  // reader just asked for. Covers the Back button as well as a link tap.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // Focus enters the panel on open so the next key press acts on the menu
  // rather than on the page behind it.
  useEffect(() => {
    if (menuOpen) firstLinkRef.current?.focus();
  }, [menuOpen]);

  /*
   * While the panel is open, Tab cycles the trigger and the panel's contents and
   * nothing else.
   *
   * The panel only opens on narrow viewports, where it covers the top of the
   * page; tabbing out of it lands the reader in content they cannot see with an
   * open menu still on screen and no obvious way back. The trigger stays inside
   * the cycle deliberately, so the way out is always one Shift+Tab away and is
   * the same control that closes the menu.
   *
   * Escape is bound on `document` rather than on the panel so it works wherever
   * focus has got to — including the trigger itself. Both listeners exist only
   * while open, so nothing else pays for them.
   */
  useEffect(() => {
    if (!menuOpen) return undefined;

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        closeMenu();
        return;
      }
      if (event.key !== "Tab") return;

      const trigger = triggerRef.current;
      const panel = panelRef.current;
      if (trigger === null || panel === null) return;

      const stops: HTMLElement[] = [trigger, ...panel.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (first === undefined || last === undefined) return;

      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen, closeMenu]);

  return (
    <div className={styles.shell}>
      {/* First focusable element by DOM order, never by a positive `tabIndex`,
        which would reorder the whole page. The `href` still carries the scroll;
        the handler carries the focus, because fragment navigation moves focus
        in some browsers and only scrolls in others — a skip link that scrolls
        without moving focus has done nothing for the reader who needs it. */}
      <a
        className={styles.skipLink}
        href="#main-content"
        onClick={() => {
          mainRef.current?.focus();
        }}
      >
        Skip to content
      </a>

      <header className={styles.sidebar}>
        <div className={styles.masthead}>
          <Link className={styles.brand} href="/">
            <CairnMark />
            <span className={styles.brandName}>Cairn</span>
          </Link>

          {/*
            A disclosure, not a dialog. The panel pushes the page down instead
            of covering it, so there is no background scroll to lock and no
            inert region to manage. Hidden by CSS on wide viewports, where the
            panel is always open and a control announcing `aria-expanded` would
            describe a state the reader cannot change.
          */}
          <button
            ref={triggerRef}
            type="button"
            className={styles.menuTrigger}
            aria-expanded={menuOpen}
            aria-controls={panelId}
            onClick={() => {
              if (menuOpen) closeMenu();
              else setMenuOpen(true);
            }}
          >
            <MenuMark open={menuOpen} />
            Menu
          </button>
        </div>

        {/* `data-open` rather than a class: the CSS reads as the state it is
          styling, and the desktop rules simply ignore the attribute. */}
        <div
          ref={panelRef}
          id={panelId}
          className={styles.panel}
          data-open={menuOpen ? "true" : "false"}
        >
          {/*
            The real workspace, from the session. A switcher when the reader
            belongs to more than one and a plain name when they do not — a
            dropdown affordance with a single option is a control that cannot do
            anything. The role beneath it is the tenant role the session already
            carries (md/15 §2.2); nothing is inferred when it is absent.
          */}
          <div className={styles.identity}>
            <WorkspaceSwitcher />
            {roleLabel !== null && (
              <p className={styles.identityRole}>
                <span className={styles.visuallyHidden}>Your role in this workspace: </span>
                <span>{roleLabel}</span>
              </p>
            )}
          </div>

          {/* Labelled: a page can hold several `nav` landmarks. */}
          <nav className={styles.nav} aria-label="Primary">
            {groups.map((group) => {
              const groupHeadingId = `${headingId}-${group.key}`;
              return (
                <div className={styles.group} key={group.key}>
                  {/*
                    A real heading, not a styled `div`. Screen reader users skim
                    by heading and by landmark; a group label that exists only as
                    small grey text is decoration, and the reader arrives at
                    "Workspace settings" with no idea it sits under Management.
                  */}
                  <h2 className={styles.groupHeading} id={groupHeadingId}>
                    {group.label}
                  </h2>
                  <ul className={styles.navList} aria-labelledby={groupHeadingId}>
                    {group.items.map((destination) => {
                      const current = isCurrent(pathname, destination);
                      const isFirst = destination.href === firstHref;
                      return (
                        <li key={destination.href}>
                          {/* `aria-current` explicitly: monochrome has no colour
                            to carry "you are here", so it must be in the
                            accessibility tree. `clsx` collapses the
                            `string | undefined` a CSS Module lookup has under
                            `noUncheckedIndexedAccess`. */}
                          <Link
                            ref={isFirst ? firstLinkRef : undefined}
                            className={clsx(styles.navLink, current && styles.navLinkCurrent)}
                            href={destination.href}
                            aria-current={current ? "page" : undefined}
                            onClick={() => {
                              if (menuOpen) closeMenu();
                            }}
                          >
                            <span className={styles.navMarker} aria-hidden="true" />
                            <NavIcon name={destination.icon} />
                            <span className={styles.navLabel}>{destination.label}</span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </nav>

          <div className={styles.account}>
            <div className={styles.accountIdentity}>
              <div className={styles.accountName}>{displayName ?? email ?? "Signed in"}</div>
              {/* The address only when it is not already the name above it. */}
              {displayName !== null && email !== null && (
                <div className={styles.accountDetail}>{email}</div>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                // Voided: `onClick` returns void, and `logOut` clears local state
                // in a `finally` regardless.
                void logOut();
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>

      {/* `tabIndex={-1}` so the skip link moves focus, not just scroll: without
        it the next Tab returns to the navigation the reader just skipped. */}
      <main ref={mainRef} id="main-content" className={styles.main} tabIndex={-1}>
        <div className={styles.content}>{children}</div>
      </main>
    </div>
  );
}
