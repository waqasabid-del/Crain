import type { NextConfig } from "next";

/**
 * Next.js configuration for the Cloudflare Workers runtime.
 *
 * The deployment target is a founder decision (md/06 §1) and the path is named
 * in §2.1: **Workers with OpenNext, not Pages.** Cloudflare's own guidance
 * changed, and choosing Pages now would mean migrating later against the
 * vendor's recommendation.
 *
 * Two platform limits shape what may be written here (md/06 §2.2):
 *
 * - **3 MiB worker bundle** on the free plan. Bundle discipline is a hard
 *   constraint rather than a preference, so nothing is added to this config
 *   that pulls a large dependency into the server bundle.
 * - **30 ms CPU per request** in subroutine mode. Cloudflare serves and routes;
 *   GCP thinks. No page here does work that belongs on the API.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Fail the build on a type error rather than shipping one. The default is
  // already this; it is written down because the escape hatch
  // (`ignoreBuildErrors`) is exactly the kind of thing that gets added at 2am
  // and never removed.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },

  /**
   * Resolve `./thing.js` to `./thing.tsx`.
   *
   * The repo imports with explicit `.js` extensions because `tsconfig.base.json`
   * uses NodeNext resolution, which requires them. TypeScript understands that
   * a `.js` specifier means the `.ts`/`.tsx` beside it; webpack does not, and
   * fails every one of those imports with "module not found".
   *
   * The alternative was to drop the extensions in `src/app` only, which would
   * mean two import conventions in one package and a rule nobody could state.
   */
  webpack: (config) => {
    config.resolve.extensionAlias = {
      ".js": [".ts", ".tsx", ".js"],
      ".jsx": [".tsx", ".jsx"],
    };
    return config;
  },

  // `next/image` needs additional configuration or Cloudflare Images on the
  // Workers runtime (md/06 §2.4). Nothing uses it yet; when something does,
  // that decision belongs here with its reasoning rather than in a component.
  images: { unoptimized: true },
};

export default nextConfig;
