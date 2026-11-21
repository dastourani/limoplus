import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../api/client';

type State<T> = { data: T | null; error: ApiError | null; loading: boolean };

/** Load data once (and again on retry). Keeps screens free of loading/error boilerplate. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });

  const started = useRef(0);
  const run = useCallback(() => {
    started.current = Date.now();
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
  // A pull to refresh on any screen reloads every screen still open (the book list on home, a book's contents in the
  // stack or beside the text), not only the one pulled. One that has just loaded is left alone.
  useEffect(() => {
    const again = () => {
      if (Date.now() - started.current > 800) run();
    };
    everyone.add(again);
    return () => {
      everyone.delete(again);
    };
  }, [run]);
  return { ...state, retry: run };
}

const everyone = new Set<() => void>();
/** Reload the data of every open screen (see useApi). */
export function refreshAll() {
  everyone.forEach((again) => again());
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
