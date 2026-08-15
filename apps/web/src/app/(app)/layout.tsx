import type { ReactNode } from "react";

import { RequireAuth } from "../../auth/RequireAuth.js";
import { AppShell } from "../../components/AppShell.js";

/**
 * The protected branch of the tree.
 *
 * A route-group layout rather than a wrapper each page remembers to include.
 * The difference matters: a per-page guard protects the pages someone
 * remembered, and the page added next month in a hurry is the one that ships
 * unprotected. Anything placed inside `(app)/` is guarded by where it lives.
 *
 * `AppShell` sits *inside* `RequireAuth`, so the navigation is never drawn for a
 * reader who is about to be redirected away.
 *
 * `/login` and `/signup` sit outside this group. They are the screens that have
 * to render without a session, and putting them inside the guard is how a login
 * page ends up redirecting to itself.
 */
/**
 * Never prerendered, never cached.
 *
 * Two reasons, and the second is the one that matters. The build fails without
 * it — the guard reads `useSearchParams`, which forces a client-side bailout
 * that static generation refuses. But the reason not to simply wrap that in a
 * Suspense boundary and carry on is that **every screen below this point is
 * authenticated and workspace-specific**, so a prerendered copy at the edge is a
 * cross-tenant read waiting to happen. Cloudflare serves and routes (md/06
 * §2.2); it must not hold a rendered brief.
 */
export const dynamic = "force-dynamic";

export default function AppLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
