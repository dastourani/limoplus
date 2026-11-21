import { useEffect, useState } from 'react';

/**
 * Staff only: see the app as a learner does (locks, prices, free labels). Lasts until the app is closed, so it is
 * never left on by accident. The API client sends `X-View-As: learner` while it is on.
 */
let on = false;
const listeners = new Set<(v: boolean) => void>();

export const viewAsLearner = () => on;

export function setViewAsLearner(value: boolean) {
  on = value;
  listeners.forEach((l) => l(value));
}

export function useViewAsLearner(): boolean {
  const [value, setValue] = useState(on);
  useEffect(() => {
    listeners.add(setValue);
    return () => {
      listeners.delete(setValue);
    };
  }, []);
  return value;
}
