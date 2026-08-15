"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import { PageHeader } from "../components/PageHeader.js";
import { EmptyState } from "../components/States.js";

/**
 * An unrecognised URL.
 *
 * Framed as the link being wrong, never the reader. Most 404s in a product like
 * this come from a stale bookmark or a link in an old email, neither of which is
 * anybody's mistake — and "page not found" plus a dead end is how someone
 * concludes the product is broken rather than that the address moved.
 */
export function NotFoundPage(): ReactNode {
  return (
    <>
      <PageHeader title="That page is not here" />
      <EmptyState title="Nothing at this address" action={<Link href="/">Go to the brief</Link>}>
        The link may be out of date, or the page may have moved since it was shared. The brief is
        the best place to pick things up again.
      </EmptyState>
    </>
  );
}
