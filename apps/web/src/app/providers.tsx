"use client";

import type { CairnClient } from "@cairn/api-client";
import type { ReactNode } from "react";

import { ApiClientContext } from "../api/context.js";
import { AuthProvider } from "../auth/AuthProvider.js";
import { ThemeProvider } from "../theme/ThemeProvider.js";

export interface ProvidersProps {
  children: ReactNode;
  /** Substituted in tests. Falls back to the real client — see api/context.ts. */
  client?: CairnClient;
}

/**
 * Everything the tree needs, in the order it needs it.
 *
 * The client first, then theme, then auth. Auth is innermost because it consumes
 * the client; theme sits outside it so that the loading and error screens auth
 * can render are already themed rather than flashing light first.
 *
 * A client component, because all three hold state and read the browser. This is
 * the boundary between the server-rendered document and the application, and it
 * is drawn as high as possible on purpose: everything below is authenticated and
 * workspace-specific, so nothing below may be rendered on the server.
 */
export function Providers({ children, client }: ProvidersProps): ReactNode {
  const themed = (
    <ThemeProvider>
      <AuthProvider>{children}</AuthProvider>
    </ThemeProvider>
  );

  return client === undefined ? (
    themed
  ) : (
    <ApiClientContext.Provider value={client}>{themed}</ApiClientContext.Provider>
  );
}
