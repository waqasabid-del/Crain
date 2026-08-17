import { ApiError } from "@cairn/api-client";

/** Error copy never blames the reader (md/05 §A.1); centralised for one voice. */

export interface DescribedError {
  message: string;
  /** Quote this to support. Rendered small, never as the headline. */
  requestId?: string;
}

/**
 * Where the failure happened, when that changes what is true about it.
 *
 * Only sign-in may describe a 401 as wrong credentials. Everywhere else a 401
 * means the session ended, and telling somebody reading their feed that their
 * password did not match is both false and alarming.
 */
export type ErrorContext = "sign-in";

/** @param action What the app was doing — "load the brief". Used in the fallback. */
export function describeError(
  error: unknown,
  action: string,
  context?: ErrorContext,
): DescribedError {
  if (error instanceof ApiError) {
    const described: DescribedError = { message: messageForApiError(error, action, context) };
    // Assigned only when present: `exactOptionalPropertyTypes` is on.
    if (error.problem.requestId !== undefined) described.requestId = error.problem.requestId;
    return described;
  }

  // A `TypeError` from `fetch` means no response reached the browser at all.
  if (error instanceof TypeError) {
    return {
      message: `CAIRN could not reach the server, so it could not ${action}. This is usually a connection problem, and retrying often works.`,
    };
  }

  return { message: `Something went wrong and CAIRN could not ${action}. Trying again may work.` };
}

function messageForApiError(error: ApiError, action: string, context?: ErrorContext): string {
  // Branch on status and the stable `type`, never on `detail`, which is prose.
  if (error.status === 401) {
    // Deliberately ambiguous between "no such address" and "wrong password":
    // saying which would confirm to a stranger that an account exists.
    return context === "sign-in"
      ? "That email address and password did not match an account. Passwords are case-sensitive."
      : "You have been signed out, so CAIRN could not " +
          action +
          ". Signing in again will fix it.";
  }
  if (error.status === 403) {
    return "This account does not have access to that. If that looks wrong, a workspace admin can change it.";
  }
  if (error.status === 404) {
    return "CAIRN could not find that. It may have been removed, or the link may point somewhere that no longer exists.";
  }
  if (error.status === 429) {
    // "Will work" was a promise this cannot keep — the client never reads
    // `Retry-After`, so it does not know how long the limit lasts.
    return `CAIRN has had a lot of requests in the last minute and has paused briefly, so it could not ${action}. Waiting a moment and trying again usually works.`;
  }
  if (error.status >= 500) {
    return `Something on CAIRN's side failed, so it could not ${action}. This is not something you did, and retrying shortly usually works.`;
  }
  return `CAIRN could not ${action}. Trying again may work.`;
}
