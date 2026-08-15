import type { Session, Workspace } from "@cairn/api-client";

const STORAGE_KEY = "cairn.workspace";

/** The remembered choice, only if it is still a membership (md/15 §3): a stored
 * id outlives the membership that justified it. */
export function resolveActiveWorkspace(session: Session | null): Workspace | null {
  if (session === null || session.workspaces.length === 0) return null;

  const stored = readStoredWorkspaceId();
  const remembered = session.workspaces.find((entry) => entry.workspace.id === stored);
  if (remembered !== undefined) return remembered.workspace;

  // Deterministic fallback: the API orders memberships by creation.
  return session.workspaces[0]?.workspace ?? null;
}

/** Guarded because `localStorage` throws outright in Safari private mode and
 * where third-party storage is blocked. */
export function readStoredWorkspaceId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeWorkspaceId(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // The choice still applies for this session; it just is not remembered.
  }
}
