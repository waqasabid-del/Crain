import type { Session, Workspace } from "@cairn/api-client";
import { createContext, useContext } from "react";

import type { DescribedError } from "../errors.js";

/** Four, not two: `loading` avoids bouncing a signed-in reader, `unavailable` is
 * a failed check rather than a signed-out one. */
export type AuthStatus = "loading" | "authenticated" | "anonymous" | "unavailable";

export type TenantRole = NonNullable<Session["workspaces"]>[number]["role"];

/** Never a substitute for `TenantRole`: nothing may branch on it to decide what data to request. */
export type WorkRole = NonNullable<NonNullable<Session["workspaces"]>[number]["workRole"]>;

export interface AuthContextValue {
  status: AuthStatus;
  session: Session | null;
  error: DescribedError | null;
  activeWorkspace: Workspace | null;
  workspaces: Workspace[];
  /** Decides what to *offer*, never what to allow; the API enforces. */
  activeRole: TenantRole | null;
  activeWorkRole: WorkRole | null;
  setWorkRole: (role: WorkRole | null) => Promise<void>;
  switchWorkspace: (workspaceId: string) => void;
  // Properties, not methods: destructuring a method trips `unbound-method`.
  logIn: (email: string, password: string) => Promise<void>;
  logOut: () => Promise<void>;
  retry: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth was called outside <AuthProvider>");
  }
  return value;
}
