import { describe, expect, it } from 'vitest';

import type { BookDetail, ProductStatus } from '../../api/endpoints';
import { firstReadableNodeId, isSectionAccessibleInBook, resolveBookCta } from '../bookAccess';

function sampleBook(): Pick<BookDetail, 'chapters'> {
  return {
    chapters: [
      {
        id: 10,
        slug: 'ch-1',
        kind: 'chapter',
        title: 'فصل ۱',
        has_overview: true,
        is_locked: false,
        sections: [
          {
            id: 101,
            slug: 'sec-1',
            kind: 'section',
            title: 'بخش اول',
            has_summary: true,
            is_locked: false,
            question_count: 5,
            flashcard_count: 3,
          },
        ],
      },
      {
        id: 20,
        slug: 'ch-2',
        kind: 'chapter',
        title: 'فصل ۲',
        has_overview: true,
        is_locked: true,
        sections: [
          {
            id: 201,
            slug: 'sec-2',
            kind: 'section',
            title: 'تغییر شدت: افزایش، بدتر شدن یا کاهش',
            has_summary: true,
            is_locked: true,
            question_count: 5,
            flashcard_count: 3,
          },
        ],
      },
    ],
  };
}

describe('isSectionAccessibleInBook', () => {
  it('allows unlocked sections and unlocked chapter overviews', () => {
    const book = sampleBook();
    expect(isSectionAccessibleInBook(book, 10)).toBe(true);
    expect(isSectionAccessibleInBook(book, 101)).toBe(true);
  });

  it('rejects stale lastSection pointing to a locked chapter or section', () => {
    const book = sampleBook();
    expect(isSectionAccessibleInBook(book, 20)).toBe(false);
    expect(isSectionAccessibleInBook(book, 201)).toBe(false);
    expect(isSectionAccessibleInBook(book, 999)).toBe(false);
  });
});

describe('firstReadableNodeId', () => {
  it('returns the unlocked first chapter overview when chapter 1 is free', () => {
    expect(firstReadableNodeId(sampleBook())).toBe(10);
  });

  it('skips locked chapters and returns an unlocked chapter or section in chapter 2 or 3', () => {
    const ch2Free: Pick<BookDetail, 'chapters'> = {
      chapters: [
        { ...sampleBook().chapters[1], id: 10 },
        { ...sampleBook().chapters[0], id: 20 },
      ],
    };
    expect(firstReadableNodeId(ch2Free)).toBe(20);

    const partialCh3: Pick<BookDetail, 'chapters'> = {
      chapters: [
        { ...sampleBook().chapters[1], id: 10 },
        {
          id: 30,
          slug: 'ch-3',
          kind: 'chapter',
          title: 'فصل ۳',
          has_overview: true,
          is_locked: true,
          sections: [
            {
              id: 301,
              slug: 'sec-3-1',
              kind: 'section',
              title: 'بخش ۳-۱',
              is_locked: true,
            },
            {
              id: 302,
              slug: 'sec-3-2',
              kind: 'section',
              title: 'بخش ۳-۲',
              is_locked: false,
            },
          ],
        },
      ],
    };
    expect(firstReadableNodeId(partialCh3)).toBe(302);
  });

  it('returns null when every chapter and section is locked', () => {
    const allLocked: Pick<BookDetail, 'chapters'> = {
      chapters: [sampleBook().chapters[1]],
    };
    expect(firstReadableNodeId(allLocked)).toBeNull();
  });
});

const makeStatus = (
  state: ProductStatus['state'],
  preview: ProductStatus['preview'] = 'none',
): ProductStatus => ({ state, preview, promotion: 'none' });

describe('resolveBookCta', () => {
  it('shows «شروع مطالعهٔ رایگان» before study and «ادامهٔ مطالعه» after study for a guest on a completely free book', () => {
    const freeBook: Pick<BookDetail, 'owned' | 'product_status' | 'chapters'> = {
      owned: false,
      product_status: makeStatus('free', 'none'),
      chapters: sampleBook().chapters,
    };

    expect(resolveBookCta(freeBook, { isAuthenticated: false, lastSection: null })).toEqual({
      kind: 'guest',
      lastTitle: null,
      targetNodeId: 10,
      buttonLabel: 'شروع مطالعهٔ رایگان',
      showUnlock: false,
    });

    expect(
      resolveBookCta(freeBook, {
        isAuthenticated: false,
        lastSection: { id: 101, title: 'بخش اول' },
      }),
    ).toEqual({
      kind: 'guest',
      lastTitle: 'بخش اول',
      targetNodeId: 101,
      buttonLabel: 'ادامهٔ مطالعه',
      showUnlock: false,
    });
  });

  it('keeps the full progress CTA for signed-in learners on a completely free book', () => {
    const freeBook: Pick<BookDetail, 'owned' | 'product_status' | 'chapters'> = {
      owned: false,
      product_status: makeStatus('free', 'none'),
      chapters: sampleBook().chapters,
    };

    expect(resolveBookCta(freeBook, { isAuthenticated: true, lastSection: null })).toEqual({
      kind: 'full',
      targetNodeId: 10,
      buttonLabel: 'شروع',
    });
  });

  it('handles paid books with sample, paid books without sample, and preparing states', () => {
    const paidSample: Pick<BookDetail, 'owned' | 'product_status' | 'chapters'> = {
      owned: false,
      product_status: makeStatus('paid', 'sample'),
      chapters: sampleBook().chapters,
    };
    expect(resolveBookCta(paidSample, { isAuthenticated: false, lastSection: null })).toEqual({
      kind: 'guest',
      lastTitle: null,
      targetNodeId: 10,
      buttonLabel: 'شروع مطالعهٔ رایگان',
      showUnlock: true,
    });

    const paidLocked: Pick<BookDetail, 'owned' | 'product_status' | 'chapters'> = {
      owned: false,
      product_status: makeStatus('paid', 'none'),
      chapters: [sampleBook().chapters[1]],
    };
    expect(resolveBookCta(paidLocked, { isAuthenticated: false, lastSection: null })).toEqual({
      kind: 'guest',
      lastTitle: null,
      targetNodeId: null,
      buttonLabel: null,
      showUnlock: true,
    });

    const preparing: Pick<BookDetail, 'owned' | 'product_status' | 'chapters'> = {
      owned: false,
      product_status: makeStatus('preparing', 'none'),
      chapters: [],
    };
    expect(resolveBookCta(preparing, { isAuthenticated: false, lastSection: null })).toEqual({
      kind: 'preparing',
    });
  });
});
