/** Same seed, same order: a shuffled set stays the same when the learner comes back. */
export function seeded<T>(items: T[], seed: number): T[] {
  let a = seed >>> 0 || 1;
  const rand = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * Practice mode. Questions turn like pages (swipe or buttons); answering is never required to move on.
 * Graded on the server one question at a time; the progress strip shows right / wrong / not answered.
 */
