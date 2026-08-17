import { ApiError } from "@cairn/api-client";
import { describe, expect, it } from "vitest";

import { describeError } from "./errors.js";

/**
 * Error copy is a product surface.
 *
 * These are the branches nothing else reaches: an audit found the 403 and 429
 * messages had no test at all, and the 401 message — written for the sign-in
 * screen — was being shown to people whose session had merely expired while
 * they were reading their feed.
 */

function apiError(status: number): ApiError {
  return new ApiError({
    type: "about:blank",
    title: "Failed",
    status,
    detail: "",
  });
}

describe("describing an API failure", () => {
  it("tells someone signing in that the credentials did not match", () => {
    const described = describeError(apiError(401), "sign you in", "sign-in");

    expect(described.message).toMatch(/did not match an account/i);
  });

  it("does not tell a reader elsewhere that their password was wrong", () => {
    // The same 401 arrives when a session simply expires. Telling somebody
    // reading their feed that their password did not match is false, and
    // alarming in a way that reads like a break-in.
    const described = describeError(apiError(401), "load the feed");

    expect(described.message).not.toMatch(/password/i);
    expect(described.message).toMatch(/signed out/i);
  });

  it("keeps a rejected sign-in ambiguous about which half was wrong", () => {
    // Saying "no such account" would confirm to a stranger that an address is
    // or is not registered.
    const described = describeError(apiError(401), "sign you in", "sign-in");

    expect(described.message).not.toMatch(/no such|not registered|unknown address/i);
  });

  it("does not promise that retrying a rate limit will work", () => {
    // The client never reads `Retry-After`, so it cannot know how long the
    // pause lasts. "Usually works" is what it can honestly say.
    const described = describeError(apiError(429), "load the feed");

    expect(described.message).not.toMatch(/will work/i);
    expect(described.message).toMatch(/usually works/i);
  });

  it("does not blame the reader's device for a rate limit", () => {
    const described = describeError(apiError(429), "load the feed");

    expect(described.message).not.toMatch(/this device/i);
  });

  it("points a refused reader at somebody who can fix it", () => {
    const described = describeError(apiError(403), "change that setting");

    expect(described.message).toMatch(/admin/i);
  });

  it("says a server failure was not the reader's doing", () => {
    const described = describeError(apiError(500), "load the brief");

    expect(described.message).toMatch(/not something you did/i);
  });

  it("names a lost connection as a connection problem", () => {
    const described = describeError(new TypeError("Failed to fetch"), "load the brief");

    expect(described.message).toMatch(/could not reach the server/i);
  });

  it("carries the request id when the server sent one", () => {
    const error = new ApiError({
      type: "about:blank",
      title: "Failed",
      status: 500,
      detail: "",
      requestId: "abc-123",
    });

    expect(describeError(error, "load the brief").requestId).toBe("abc-123");
  });

  it("never leaks a status code or an exception name to the reader", () => {
    for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
      const { message } = describeError(apiError(status), "load the brief");
      expect(message).not.toMatch(new RegExp(String(status)));
      expect(message).not.toMatch(/error|exception/i);
    }
  });
});
