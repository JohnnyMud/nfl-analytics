import { useEffect, useState } from "react";

import { ApiError } from "../api/client";

export type ApiState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: ApiError | Error };

const LOADING: ApiState<never> = { status: "loading", data: null, error: null };

/**
 * Run one GET when `key` changes. Stale responses from a superseded key are
 * dropped, so navigating between players cannot paint the wrong data.
 *
 * `fetcher` is looked up at request time; only `key` drives re-fetching.
 * Pass `key = null` to hold in the loading state without requesting.
 */
export function useApi<T>(
  key: string | null,
  fetcher: () => Promise<T>,
): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>(LOADING);

  useEffect(() => {
    setState(LOADING);
    if (key === null) {
      return;
    }
    let cancelled = false;
    fetcher()
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data, error: null });
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) {
          return;
        }
        const error =
          caught instanceof Error ? caught : new Error(String(caught));
        setState({ status: "error", data: null, error });
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  return state;
}

export function isNotFound(error: Error | null): boolean {
  return error instanceof ApiError && error.status === 404;
}
