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

/** Destinations that exist today (md/15 §4.1). "Trust and privacy" is in primary
 * navigation for everybody — md/05 §B.6 requires a permanent, visible page.
 * `admin` avoids a dead end and is never security; the API enforces. */
const DESTINATIONS = [
  { href: "/", label: "Brief", exact: true, admin: false },
  { href: "/me", label: "My week", exact: false, admin: false },
  { href: "/archive", label: "Archive", exact: false, admin: false },
  { href: "/feed", label: "Feed", exact: false, admin: false },
  { href: "/people", label: "People", exact: false, admin: false },
  { href: "/admin", label: "Workspace", exact: false, admin: true },
  { href: "/trust", label: "Trust and privacy", exact: false, admin: false },
  { href: "/settings", label: "Settings", exact: false, admin: false },
] as const;

/** `exact` on the brief only: without it "/" prefix-matches every path and two
 * links claim `aria-current="page"` at once. */
function isCurrent(pathname: string, destination: (typeof DESTINATIONS)[number]): boolean {
  return destination.exact
    ? pathname === destination.href
    : pathname === destination.href || pathname.startsWith(`${destination.href}/`);
}

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
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const firstLinkRef = useRef<HTMLAnchorElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  const visible = DESTINATIONS.filter(
    (destination) => !destination.admin || activeRole === "owner" || activeRole === "admin",
  );
  const user = session?.user ?? null;

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
  // rather than on the page behind it. Non-modal, so Tab still leaves freely.
  useEffect(() => {
    if (menuOpen) firstLinkRef.current?.focus();
  }, [menuOpen]);

  // Escape, from wherever focus has got to. Bound on `document` rather than on
  // the header because the panel is not modal: focus is free to leave it, and a
  // reader who has tabbed into the page still expects Escape to dismiss the
  // thing they opened. Only listening while open, so nothing else pays for it.
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") closeMenu();
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
            of covering it, so there is nothing behind it to trap focus against
            and no scroll to lock — the two obligations a drawer gets wrong.
            Hidden by CSS on wide viewports, where the panel is always open.
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
        <div id={panelId} className={styles.panel} data-open={menuOpen ? "true" : "false"}>
          <WorkspaceSwitcher />

          {/* Labelled: a page can hold several `nav` landmarks. */}
          <nav className={styles.nav} aria-label="Primary">
            <ul className={styles.navList}>
              {visible.map((destination, index) => {
                const current = isCurrent(pathname, destination);
                return (
                  <li key={destination.href}>
                    {/* `aria-current` explicitly: monochrome has no colour to
                      carry "you are here", so it must be in the accessibility
                      tree. `clsx` collapses the `string | undefined` a CSS Module
                      lookup has under `noUncheckedIndexedAccess`. */}
                    <Link
                      ref={index === 0 ? firstLinkRef : undefined}
                      className={clsx(styles.navLink, current && styles.navLinkCurrent)}
                      href={destination.href}
                      aria-current={current ? "page" : undefined}
                      onClick={() => {
                        if (menuOpen) closeMenu();
                      }}
                    >
                      {destination.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className={styles.account}>
            <div className={styles.accountIdentity}>
              <div className={styles.accountName}>
                {user?.displayName ?? user?.email ?? "Signed in"}
              </div>
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
