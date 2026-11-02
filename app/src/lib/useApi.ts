import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';

type State<T> = { data: T | null; error: ApiError | null; loading: boolean };

/** Load data once (and again on retry). Keeps screens free of loading/error boilerplate. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });

  const run = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    load()
      // The same answer as before keeps the same object, so nothing on the screen is drawn again for it.
      .then((data) => setState((s) => ({ data: s.data !== null && same(s.data, data) ? s.data : data, error: null, loading: false })))
      .catch((error: unknown) =>
        setState({
          data: null,
          loading: false,
          error: error instanceof ApiError ? error : new ApiError(0, 'error', 'خطای ناشناخته. دوباره تلاش کنید.'),
        }),
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);
  return { ...state, retry: run };
}

/** For setState: keep the old value when the new one is the same, so the screen is not drawn again. */
export function keepIfSame<T>(next: T): (prev: T) => T {
  return (prev) => (same(prev, next) ? prev : next);
}

function same(a: unknown, b: unknown): boolean {
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}
