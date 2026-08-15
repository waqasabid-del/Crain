import type { CairnClient } from "@cairn/api-client";
import { createContext, useContext } from "react";

import { client } from "./client.js";

/**
 * The API client, reachable from anywhere without importing the module.
 *
 * Unlike the auth and theme contexts, this one has a real default — the module
 * singleton — rather than `null`. A component rendered without the provider
 * should talk to the real API, which is the correct behaviour in the app; the
 * provider exists so that a test can substitute a stub in one place instead of
 * mocking a module in every file that transitively imports it.
 *
 * The alternative considered and rejected: passing the client down as a prop
 * from the root. That works until the fourth screen needs it, at which point
 * every intermediate component has a prop it does not use, and the next screen
 * quietly imports the singleton instead — which is the version that makes a real
 * network call from a test.
 */
export const ApiClientContext = createContext<CairnClient>(client);

export function useApiClient(): CairnClient {
  return useContext(ApiClientContext);
}
