/**
 * Shared domain types. Most types will be generated from the OpenAPI schema
 * (md/06-infrastructure.md §6A.2); hand-written ones are limited to concepts
 * that exist on both sides of the boundary independently of any endpoint.
 */

/** Certainty tiers. Categorical, never numeric: a "73% confident" badge invites
 * false precision. Internal numeric confidence never reaches the interface.
 * @see md/05-ux-design-privacy.md §A.2.1 */
export const CERTAINTY_TIERS = ["verified", "observed", "suggested"] as const;

export type Certainty = (typeof CERTAINTY_TIERS)[number];

/** Tenant roles. Four, deliberately; custom roles are deferred. Admin governs
 * configuration, never surveillance depth — no role grants deeper visibility
 * into an individual than that individual has.
 * @see md/15-system-roles-and-surfaces.md §2.2, §2.3 */
export const TENANT_ROLES = ["owner", "admin", "member", "viewer"] as const;

export type TenantRole = (typeof TENANT_ROLES)[number];

/** The four activity categories every source normalizes into.
 * @see md/12-data-model.md §3 */
export const ACTIVITY_CATEGORIES = ["code", "conversation", "meeting", "document"] as const;

export type ActivityCategory = (typeof ACTIVITY_CATEGORIES)[number];

/** Branded, so an arbitrary string cannot be passed where a tenant id is
 * required: a job that loses this reads across tenants rather than failing.
 * @see md/06-infrastructure.md §4.3 */
export type TenantId = string & { readonly __brand: "TenantId" };

export function asTenantId(value: string): TenantId {
  // Trimmed, to match the Python side, which rejects "   ".
  if (value.trim().length === 0) {
    throw new Error("Tenant ID cannot be empty");
  }
  return value as TenantId;
}

/** Event schema types, generated from the Python model.
 * @see apps/api/src/cairn_api/events/schema.py — the source of truth
 * @see `make schema` — regenerate after changing it */
export type * from "./generated/activity-event.js";
