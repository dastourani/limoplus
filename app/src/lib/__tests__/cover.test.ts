import { describe, expect, it } from 'vitest';

import { coverRatingLabel } from '../cover';

describe('coverRatingLabel', () => {
  it('formats approved ratings with Persian digits and slash-comma decimal separator', () => {
    expect(coverRatingLabel(4.8, 12)).toBe('۴٫۸');
    expect(coverRatingLabel(5, 3)).toBe('۵');
    expect(coverRatingLabel(4.0, 1)).toBe('۴');
    expect(coverRatingLabel(4.74, 2)).toBe('۴٫۷');
  });

  it('returns null when a book has no approved reviews or invalid rating', () => {
    expect(coverRatingLabel(null, 0)).toBeNull();
    expect(coverRatingLabel(undefined, 0)).toBeNull();
    expect(coverRatingLabel(5, 0)).toBeNull();
    expect(coverRatingLabel(0, 5)).toBeNull();
    expect(coverRatingLabel(Number.NaN, 1)).toBeNull();
  });
});
