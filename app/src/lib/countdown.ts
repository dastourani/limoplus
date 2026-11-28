import { useEffect, useState } from 'react';

import { toPersianDigits } from '../theme';

/** «۳ روز و ۴ ساعت مانده» while more than a day is left; a live «۰۴:۱۲:۳۰» in the last 24 hours; null when over. */
export function countdownText(msLeft: number): string | null {
  if (msLeft <= 0) return null;
  const s = Math.floor(msLeft / 1000);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  if (days >= 3) return `${toPersianDigits(days)} روز مانده`;
  if (days >= 1) return hours ? `${toPersianDigits(days)} روز و ${toPersianDigits(hours)} ساعت مانده` : `${toPersianDigits(days)} روز مانده`;
  const pad = (n: number) => toPersianDigits(String(n).padStart(2, '0'));
  return `${pad(hours)}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

/** The countdown's text, refreshed by itself: once a second in the last day, once a minute before. Only this text
 * redraws, never the banner around it (a whole banner redrawn every second made the home page stutter). */
export function useCountdown(endsAt: string | null | undefined, offset = 0): string | null {
  const left = () => (endsAt ? countdownText(Date.parse(endsAt) - (Date.now() + offset)) : null);
  const [text, setText] = useState(left);
  useEffect(() => {
    if (!endsAt) return;
    let timer: ReturnType<typeof setTimeout>;
    const step = () => {
      setText(left());
      const ms = Date.parse(endsAt) - (Date.now() + offset);
      if (ms > 0) timer = setTimeout(step, ms > 86_400_000 ? 60_000 : 1000);
    };
    step();
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endsAt, offset]);
  return text;
}
