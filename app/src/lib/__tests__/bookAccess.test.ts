import { describe, expect, it } from 'vitest';

import type { BookDetail, ProductStatus } from '../../api/endpoints';
import {
  firstReadableNodeId,
  isAmbiguous403,
  isNodeLockedInBook,
  isSectionAccessibleInBook,
  lockedCtaLabel,
  lockedPayloadFromBook,
  productStateNote,
  resolveBookCta,
  resolveSectionForbidden,
} from '../bookAccess';
import { errorPresentation } from '../errors';

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

function fullBookDetail(overrides: Partial<BookDetail> = {}): BookDetail {
  return {
    id: 1,
    slug: 'math-1',
    title: 'ریاضی عمومی ۱',
    title_en: 'Calculus 1',
    author: 'دکتر نمونه',
    edition: '۱۴۰۴',
    motif: 'grid',
    drawing: null,
    cover: null,
    is_coming_soon: false,
    product_status: makeStatus('paid', 'sample'),
    price: 200000,
    regular_price: 250000,
    discount: null,
    chapter_count: 2,
    section_count: 2,
    free_chapter: 1,
    owned: false,
    progress: null,
    notify: false,
    single_sale_only: false,
    done_card_count: 0,
    about: '',
    majors: ['math'],
    chapters: sampleBook().chapters,
    done_ids: [],
    ...overrides,
  };
}

describe('locked error recovery & errorPresentation', () => {
  it('buyer + unlocked section + ambiguous 403 -> shows restricted error, never a purchase prompt', () => {
    const buyerBook = fullBookDetail({
      owned: true,
      access: 'purchase',
      chapters: sampleBook().chapters.map((ch) => ({
        ...ch,
        is_locked: false,
        sections: ch.sections.map((s) => ({ ...s, is_locked: false })),
      })),
    });

    const result = resolveSectionForbidden(
      { status: 403, code: 'error', message: 'اجازه‌ی این کار را ندارید.', data: {} },
      { nodeId: 201, book: buyerBook },
    );

    expect(result).toEqual({
      kind: 'restricted',
      message: 'اجازه‌ی این کار را ندارید.',
    });
    expect(isNodeLockedInBook(buyerBook, 201)).toBe(false);
  });

  it('guest + confirmed locked section of the same book + ambiguous 403 -> shows lock and single-sale CTA when single_sale_only', () => {
    const guestBook = fullBookDetail({
      owned: false,
      single_sale_only: true,
    });

    const result = resolveSectionForbidden(
      { status: 403, code: 'error', message: 'اجازه‌ی این کار را ندارید.', data: {} },
      { nodeId: 201, book: guestBook },
    );

    expect(result.kind).toBe('locked');
    if (result.kind === 'locked') {
      expect(result.book.slug).toBe('math-1');
      expect(result.book.price).toBe(200000);
      expect(result.book.single_sale_only).toBe(true);
      expect(lockedCtaLabel(result.book.single_sale_only)).toBe('خرید کتاب');
    }
    expect(lockedCtaLabel(false)).toBe('خرید یا اشتراک');
  });

  it('explicit code=locked with book payload shows lock screen directly, while ambiguous 403 without matching locked node falls back to restricted', () => {
    const explicit = resolveSectionForbidden(
      {
        status: 403,
        code: 'locked',
        message: 'این بخش در نسخه‌ی کامل کتاب است.',
        data: {
          book: {
            slug: 'physics-1',
            title: 'فیزیک ۱',
            price: 180000,
            regular_price: 180000,
            discount: null,
            product_status: makeStatus('paid', 'none'),
            single_sale_only: true,
          },
        },
      },
      { nodeId: 201, book: null },
    );
    expect(explicit.kind).toBe('locked');
    if (explicit.kind === 'locked') {
      expect(lockedCtaLabel(explicit.book.single_sale_only)).toBe('خرید کتاب');
    }

    // Node 999 is not in guestBook -> never show purchase prompt for an unrelated section.
    const unknownNode = resolveSectionForbidden(
      { status: 403, code: 'error', data: {} },
      { nodeId: 999, book: fullBookDetail() },
    );
    expect(unknownNode.kind).toBe('restricted');

    // No book metadata loaded at all -> never guess price or status.
    const missingBook = resolveSectionForbidden(
      { status: 403, code: 'error', data: {} },
      { nodeId: 201, book: null },
    );
    expect(missingBook.kind).toBe('restricted');
  });

  it('403 with specific non-locked server reason + locked section in book -> preserves server message, no purchase prompt', () => {
    const guestBook = fullBookDetail({ owned: false });
    expect(isNodeLockedInBook(guestBook, 201)).toBe(true);

    const specific403 = {
      status: 403,
      code: 'user_inactive',
      message: 'حساب کاربری شما موقتاً غیرفعال شده است.',
      data: { code: 'user_inactive', message: 'حساب کاربری شما موقتاً غیرفعال شده است.' },
    };

    expect(isAmbiguous403(specific403)).toBe(false);
    expect(resolveSectionForbidden(specific403, { nodeId: 201, book: guestBook })).toEqual({
      kind: 'restricted',
      message: 'حساب کاربری شما موقتاً غیرفعال شده است.',
    });
  });

  it('extracts locked payload and state notes from book metadata', () => {
    const info = lockedPayloadFromBook({
      slug: 'math-1',
      title: 'ریاضی عمومی ۱',
      price: 200000,
      regular_price: 250000,
      discount: null,
      product_status: makeStatus('paid', 'sample'),
      single_sale_only: true,
    });
    expect(info.slug).toBe('math-1');
    expect(info.price).toBe(200000);
    expect(info.regular_price).toBe(250000);
    expect(info.single_sale_only).toBe(true);
    expect(productStateNote('coming_soon')).toContain('به‌زودی');
    expect(productStateNote('paid')).toBeNull();
  });

  it('never shows «ارتباط برقرار نشد» for 403 or 404 errors', () => {
    expect(errorPresentation(403)).toEqual({ title: 'دسترسی محدود', icon: 'lock' });
    expect(errorPresentation(404)).toEqual({ title: 'پیدا نشد', icon: 'search' });
    expect(errorPresentation(500)).toEqual({ title: 'ارتباط برقرار نشد', icon: 'cloud-off' });
    expect(errorPresentation(0)).toEqual({ title: 'ارتباط برقرار نشد', icon: 'cloud-off' });
    expect(errorPresentation(undefined)).toEqual({ title: 'ارتباط برقرار نشد', icon: 'cloud-off' });
  });
});
