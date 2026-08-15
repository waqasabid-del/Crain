import { ApiError } from "@cairn/api-client";

/** Error copy never blames the reader (md/05 §A.1); centralised for one voice. */

export interface DescribedError {
  message: string;
  /** Quote this to support. Rendered small, never as the headline. */
  requestId?: string;
}

/** @param action What the app was doing — "load the brief". Used in the fallback. */
export function describeError(error: unknown, action: string): DescribedError {
  if (error instanceof ApiError) {
    const described: DescribedError = { message: messageForApiError(error, action) };
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

function messageForApiError(error: ApiError, action: string): string {
  // Branch on status and the stable `type`, never on `detail`, which is prose.
  if (error.status === 401) {
    return "That email address and password did not match an account. Passwords are case-sensitive, and it is worth checking the address for an autocorrect.";
  }
  if (error.status === 403) {
    return "This account does not have access to that. If that looks wrong, a workspace admin can change it.";
  }
  if (error.status === 404) {
    return "CAIRN could not find that. It may have been removed, or the link may point somewhere that no longer exists.";
  }
  if (error.status === 429) {
    return "There have been a lot of attempts from this device in the last minute, so CAIRN has paused sign-in briefly. Waiting a moment and trying again will work.";
  }
  if (error.status >= 500) {
    return `Something on CAIRN's side failed, so it could not ${action}. This is not something you did, and retrying shortly usually works.`;
  }
  return `CAIRN could not ${action}. Trying again may work.`;
}
