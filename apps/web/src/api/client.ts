import { createClient, type CairnClient } from "@cairn/api-client";

import { API_BASE_URL } from "../env.js";

/**
 * The client this app talks to the API through.
 *
 * A module-level instance rather than one per component: it holds no state, so
 * there is nothing to share incorrectly, and a factory call in a render would
 * make a new object identity every frame — which turns every `useEffect` that
 * depends on it into an infinite loop.
 *
 * **Nothing here hand-rolls `fetch`.** @cairn/api-client already sets
 * `credentials: "include"`, which is what attaches the `HttpOnly` session
 * cookie, and it already turns a problem document into a typed `ApiError`. A
 * second, local fetch helper would be a second place for those decisions to
 * drift, and the one that drifts is always the one that forgets credentials.
 *
 * Note what is deliberately *absent*: a CSRF token header. The API defends
 * state-changing requests with `SameSite=Lax` plus an `Origin` check
 * (apps/api/src/cairn_api/api/middleware.py — `CsrfOriginMiddleware`). The
 * browser sets `Origin` itself and script cannot forge it, so there is nothing
 * for this layer to send. Adding a token would mean a token endpoint, client
 * plumbing and a new failure mode, all defending a request the origin check
 * already refuses.
 */
export const client: CairnClient = createClient({ baseUrl: API_BASE_URL });
