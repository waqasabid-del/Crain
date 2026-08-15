import { defineCloudflareConfig } from "@opennextjs/cloudflare";

/**
 * OpenNext's Cloudflare adapter.
 *
 * Deliberately minimal. Incremental cache, tag cache and queue adapters all
 * have Cloudflare-backed implementations (R2, D1, Durable Objects), and none of
 * them is configured because **no page in this app is cached at the edge**: every
 * screen is authenticated and workspace-specific, so a shared cache would be a
 * cross-tenant read waiting to happen — the one failure this system is built
 * hardest against.
 *
 * If a public marketing surface is added later it gets its own configuration
 * here, with that reasoning revisited rather than inherited.
 */
export default defineCloudflareConfig();
