import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@cairn/ui/styles";

import { Providers } from "./providers.js";

export const metadata: Metadata = {
  title: "CAIRN",
  description: "What your team actually did, with the evidence attached.",
};

/** No screen below may be server-rendered or edge-cached — all are authenticated and
 * workspace-specific (md/06 §2.2). `suppressHydrationWarning` covers `data-theme`,
 * which the pre-paint script stamps before React hydrates. */
export default function RootLayout({ children }: { children: ReactNode }): ReactNode {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Inline and blocking so the stored theme applies before first paint; deferring
            it paints the default palette first. Literal content, so nothing is injected. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                var stored = localStorage.getItem("cairn.theme");
                var preference = stored === "light" || stored === "dark" ? stored : null;
                if (preference) document.documentElement.dataset.theme = preference;
              } catch (_) {}
            `,
          }}
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
