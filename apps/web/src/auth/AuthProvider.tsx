import type { Session } from "@cairn/api-client";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { useApiClient } from "../api/context.js";
import { describeError, type DescribedError } from "../errors.js";
import { AuthContext, type AuthContextValue, type AuthStatus, type WorkRole } from "./context.js";
import { resolveActiveWorkspace, storeWorkspaceId } from "./workspace.js";

export interface AuthProviderProps {
  children: ReactNode;
}

interface AuthState {
  status: AuthStatus;
  session: Session | null;
  error: DescribedError | null;
}

const LOADING: AuthState = { status: "loading", session: null, error: null };
const ANONYMOUS: AuthState = { status: "anonymous", session: null, error: null };

/** Holds the answer to "who is this". The session cookie is `HttpOnly`, so the
 * frontend cannot read it and must ask the API — which is why `loading` is a
 * first-class state everywhere below. */
export function AuthProvider({ children }: AuthProviderProps): ReactNode {
  const client = useApiClient();
  const [state, setState] = useState<AuthState>(LOADING);
  // A counter, not a boolean: a second failure must be able to trigger a third
  // attempt, and a boolean already true re-runs nothing.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    // The abort alone does not prevent a state update: an in-flight response can
    // resolve before it is observed.
    let live = true;

    setState(LOADING);
    client
      .getSession({ signal: controller.signal })
      .then((session) => {
        if (!live) return;
        setState(session === null ? ANONYMOUS : { status: "authenticated", session, error: null });
      })
      .catch((error: unknown) => {
        // An abort is tidying up, not a failure worth reporting.
        if (!live || controller.signal.aborted) return;
        setState({
          status: "unavailable",
          session: null,
          error: describeError(error, "check who you are signed in as"),
        });
      });

    return () => {
      live = false;
      controller.abort();
    };
  }, [client, attempt]);

  const logIn = useCallback(
    async (email: string, password: string): Promise<void> => {
      // Not caught here: the login form is where a sign-in failure belongs,
      // beside the fields the reader would change.
      const session = await client.logIn({ email, password });
      setState({ status: "authenticated", session, error: null });
    },
    [client],
  );

  const logOut = useCallback(async (): Promise<void> => {
    try {
      await client.logOut();
    } finally {
      // `finally`, so a failed revoke still clears the app: the cookie is
      // `HttpOnly` and cannot be deleted here, but leaving the reader apparently
      // signed in would invite them to walk away from a shared machine.
      setState(ANONYMOUS);
    }
  }, [client]);

  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  // An id, not a `Workspace`, so a session refresh cannot leave a stale copy.
  const [chosenId, setChosenId] = useState<string | null>(null);

  const workspaces = useMemo(
    () => (state.session?.workspaces ?? []).map((entry) => entry.workspace),
    [state.session],
  );

  const activeWorkspace = useMemo(() => {
    const chosen = workspaces.find((workspace) => workspace.id === chosenId);
    return chosen ?? resolveActiveWorkspace(state.session);
  }, [workspaces, chosenId, state.session]);

  // Read from the session, never stored, so a role change takes effect on the
  // next session check rather than persisting until sign-out.
  const activeRole = useMemo(
    () =>
      (state.session?.workspaces ?? []).find((entry) => entry.workspace.id === activeWorkspace?.id)
        ?.role ?? null,
    [state.session, activeWorkspace],
  );

  const activeWorkRole = useMemo(
    () =>
      (state.session?.workspaces ?? []).find((entry) => entry.workspace.id === activeWorkspace?.id)
        ?.workRole ?? null,
    [state.session, activeWorkspace],
  );

  /** Updated in place rather than re-fetched: the answer decides where the
   * reader goes next, and a round trip would change the screen under them. */
  const setWorkRole = useCallback(
    async (role: WorkRole | null): Promise<void> => {
      const workspaceId = activeWorkspace?.id;
      if (workspaceId === undefined) return;

      await client.setWorkRole(workspaceId, role);
      setState((current) =>
        current.session === null
          ? current
          : {
              ...current,
              session: {
                ...current.session,
                workspaces: current.session.workspaces.map((entry) =>
                  entry.workspace.id === workspaceId ? { ...entry, workRole: role } : entry,
                ),
              },
            },
      );
    },
    [client, activeWorkspace],
  );

  const switchWorkspace = useCallback(
    (workspaceId: string) => {
      // Membership is checked before storing: an id from a stale link would
      // otherwise be re-applied on every load.
      if (!workspaces.some((workspace) => workspace.id === workspaceId)) return;
      storeWorkspaceId(workspaceId);
      setChosenId(workspaceId);
    },
    [workspaces],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      status: state.status,
      session: state.session,
      error: state.error,
      activeWorkspace,
      workspaces,
      activeRole,
      activeWorkRole,
      setWorkRole,
      switchWorkspace,
      logIn,
      logOut,
      retry,
    }),
    [
      state,
      activeWorkspace,
      workspaces,
      activeRole,
      activeWorkRole,
      setWorkRole,
      switchWorkspace,
      logIn,
      logOut,
      retry,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
