"use client";

import { Button } from "@cairn/ui";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
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

export function AppShell({ children }: { children: ReactNode }): ReactNode {
  const { session, logOut, activeRole } = useAuth();
  const pathname = usePathname();

  const visible = DESTINATIONS.filter(
    (destination) => !destination.admin || activeRole === "owner" || activeRole === "admin",
  );
  const user = session?.user ?? null;

  return (
    <div className={styles.shell}>
      {/* First focusable element by DOM order, never by a positive `tabIndex`,
        which would reorder the whole page. */}
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>

      <header className={styles.sidebar}>
        <Link className={styles.brand} href="/">
          <CairnMark />
          <span className={styles.brandName}>Cairn</span>
        </Link>

        <WorkspaceSwitcher />

        {/* Labelled: a page can hold several `nav` landmarks. */}
        <nav className={styles.nav} aria-label="Primary">
          <ul className={styles.navList}>
            {visible.map((destination) => {
              const current = isCurrent(pathname, destination);
              return (
                <li key={destination.href}>
                  {/* `aria-current` explicitly: monochrome has no colour to
                    carry "you are here", so it must be in the accessibility
                    tree. `clsx` collapses the `string | undefined` a CSS Module
                    lookup has under `noUncheckedIndexedAccess`. */}
                  <Link
                    className={clsx(styles.navLink, current && styles.navLinkCurrent)}
                    href={destination.href}
                    aria-current={current ? "page" : undefined}
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
      </header>

      {/* `tabIndex={-1}` so the skip link moves focus, not just scroll: without
        it the next Tab returns to the navigation the reader just skipped. */}
      <main id="main-content" className={styles.main} tabIndex={-1}>
        <div className={styles.content}>{children}</div>
      </main>
    </div>
  );
}
