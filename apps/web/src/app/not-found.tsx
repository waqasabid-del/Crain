import type { ReactNode } from "react";

import { NotFoundPage } from "../routes/NotFoundPage.js";

/**
 * The catch-all, rendered without the shell.
 *
 * A signed-out visitor following a stale link would otherwise be redirected to
 * sign in only to find out the link was broken. Showing the 404 immediately,
 * with a way home, is the shorter path to the truth — and the page itself is
 * public, so there is nothing to protect.
 */
export default function NotFound(): ReactNode {
  return <NotFoundPage />;
}
