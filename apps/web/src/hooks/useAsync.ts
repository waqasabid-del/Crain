import { useCallback, useEffect, useState } from "react";

import { describeError, type DescribedError } from "../errors.js";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "failed"; error: DescribedError };

export interface AsyncResult<T> {
  state: AsyncState<T>;
  reload: () => void;
}

/** One asynchronous read. **`run` must be stable** — wrap it in `useCallback` at
 * the call site, or the effect re-runs every render and the page loads forever. */
export function useAsync<T>(
  run: (signal: AbortSignal) => Promise<T>,
  /** Slots into error copy — "load the brief". See errors.ts. */
  action: string,
): AsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;

    setState({ status: "loading" });
    run(controller.signal)
      .then((data) => {
        if (live) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        // An abort is this hook cleaning up, not a failure worth showing.
        if (!live || controller.signal.aborted) return;
        setState({ status: "failed", error: describeError(error, action) });
      });

    return () => {
      live = false;
      controller.abort();
    };
  }, [run, action, attempt]);

  const reload = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  return { state, reload };
}
