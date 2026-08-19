/**
 * Build-time configuration.
 *
 * Next inlines `process.env.NEXT_PUBLIC_*` at build time, so these are not
 * secrets and must never hold one — everything here ends up as a literal in a
 * bundle any visitor can read. That is the reason the session lives in an `HttpOnly` cookie
 * the frontend cannot see rather than in a token this layer would have to hold.
 *
 * Read once, here, rather than at each use site. A typo in an env name spread
 * across the app fails as `undefined` at whichever screen happens to be opened
 * first; centralising it means the failure is one place and one lookup.
 */

/**
 * Origin of the CAIRN API, with no trailing slash.
 *
 * Defaults to the port `make serve` uses. A default that works out of the box
 * matters more than it looks: the alternative is every new developer's first
 * experience being a blank screen and a CORS error in the console.
 */
export const API_BASE_URL: string = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Where the Brief and Feed screens get their content.
 *
 * `api` — the real endpoints (`GET /v1/workspaces/{id}/brief`, `/facts`).
 * `sample` — a fixed, obviously-labelled example, so the screens can be designed
 * and reviewed before the endpoints land.
 *
 * **`api` is the default, deliberately.** Sample content that appears without
 * being asked for is the failure mode this setting exists to avoid: a product
 * whose entire promise is "every claim links to its source" cannot ship a screen
 * that quietly invents claims. When `sample` is on, the screen says so in a
 * banner that cannot be dismissed — see `BriefPage`.
 */
export type ContentSource = "api" | "sample";

export const CONTENT_SOURCE: ContentSource =
  process.env.NEXT_PUBLIC_CONTENT_SOURCE === "sample" ? "sample" : "api";
