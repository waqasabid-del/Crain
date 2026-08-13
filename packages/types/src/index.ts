/**
 * Shared domain types.
 *
 * Most types here will be GENERATED from the API's OpenAPI schema
 * (md/06-infrastructure.md §6A.2) once the API exists. Hand-written types are
 * limited to concepts that exist on both sides of the boundary independently
 * of any endpoint.
 */

/**
 * Certainty tiers.
 *
 * Categorical, never numeric. A "73% confident" badge looks rigorous, means
 * nothing to a non-technical reader, and invites false precision. Internal
 * numeric confidence exists for thresholds and evaluation, but it never
 * reaches this type or the interface.
 *
 * @see md/05-ux-design-privacy.md §A.2.1
 */
export const CERTAINTY_TIERS = ["verified", "observed", "suggested"] as const;

export type Certainty = (typeof CERTAINTY_TIERS)[number];

/**
 * Tenant roles.
 *
 * Deliberately limited to four. Role explosion is a documented trap — 500
 * customers with 10 custom roles each produces 5,000 roles nobody can reason
 * about. Custom roles are deferred until an enterprise customer requires them.
 *
 * Note that Admin governs *configuration*, never *surveillance depth*: no role
 * grants deeper visibility into an individual than that individual has.
 *
 * @see md/15-system-roles-and-surfaces.md §2.2, §2.3
 */
export const TENANT_ROLES = ["owner", "admin", "member", "viewer"] as const;

export type TenantRole = (typeof TENANT_ROLES)[number];

/**
 * The four activity categories every source normalizes into.
 *
 * @see md/12-data-model.md §3
 */
export const ACTIVITY_CATEGORIES = ["code", "conversation", "meeting", "document"] as const;

export type ActivityCategory = (typeof ACTIVITY_CATEGORIES)[number];

/**
 * Branded type for tenant identifiers.
 *
 * Tenant ID is the single most important field in the system — a background
 * job that loses it silently reads across tenants rather than failing loudly.
 * Branding makes it impossible to pass an arbitrary string where a tenant ID
 * is required, catching a whole class of mistake at compile time.
 *
 * @see md/06-infrastructure.md §4.3
 */
export type TenantId = string & { readonly __brand: "TenantId" };

export function asTenantId(value: string): TenantId {
  if (value.length === 0) {
    throw new Error("Tenant ID cannot be empty");
  }
  return value as TenantId;
}

/**
 * Event schema types, generated from the Python model.
 *
 * @see apps/api/src/cairn_api/events/schema.py — the source of truth
 * @see `make schema` — regenerate after changing it
 */
export type * from "./generated/activity-event.js";
