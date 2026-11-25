import { describe, expect, it } from 'vitest';

import type { ProductStatus } from '../../api/endpoints';
import { accessLabel, shelfLabel } from '../access';

const status = (
  state: ProductStatus['state'],
  preview: ProductStatus['preview'] = 'none',
): ProductStatus => ({ state, preview, promotion: 'none' });

describe('accessLabel', () => {
  it('returns null when book is not owned and user is not editor', () => {
    expect(accessLabel({ owned: false, access: null })).toBeNull();
  });

  it('maps each owned/editor access type to its Persian label', () => {
    expect(accessLabel({ owned: false, access: 'editor' })).toBe('دوره اختصاصی');
    expect(accessLabel({ owned: true, access: 'subscription' })).toBe('با اشتراک');
    expect(accessLabel({ owned: true, access: 'staff' })).toBe('دسترسی مدیر');
    expect(accessLabel({ owned: true, access: 'gift' })).toBe('دوره اختصاصی');
    expect(accessLabel({ owned: true, access: 'purchase' })).toBe('خریداری شده');
  });
});

describe('shelfLabel', () => {
  it('prioritizes coming_soon over everything else', () => {
    expect(
      shelfLabel({
        owned: true,
        access: 'purchase',
        product_status: status('coming_soon', 'sample'),
        free_chapter: 1,
      }),
    ).toEqual({ text: 'به‌زودی', kind: 'soon' });
  });

  it('shows access label before free/sample labels when owned', () => {
    expect(
      shelfLabel({
        owned: true,
        access: 'subscription',
        product_status: status('paid', 'sample'),
        free_chapter: 1,
      }),
    ).toEqual({ text: 'با اشتراک', kind: 'access' });
  });

  it('distinguishes single free chapter ordinal from multiple free chapters', () => {
    expect(
      shelfLabel({
        owned: false,
        product_status: status('paid', 'sample'),
        free_chapter: 2,
        free_chapters: 1,
      }),
    ).toEqual({ text: 'فصل دوم رایگان', kind: 'free' });

    expect(
      shelfLabel({
        owned: false,
        product_status: status('paid', 'sample'),
        free_chapter: 1,
        free_chapters: 3,
      }),
    ).toEqual({ text: '۳ فصل رایگان', kind: 'free' });
  });

  it('maps preparing, unpriced, unavailable, and paid locked states', () => {
    expect(shelfLabel({ owned: false, product_status: status('preparing'), free_chapter: null })).toEqual({
      text: 'در حال برنامه‌ریزی',
      kind: 'planning',
    });
    expect(shelfLabel({ owned: false, product_status: status('unpriced'), free_chapter: null })).toEqual({
      text: 'قیمت تعیین نشده',
      kind: 'locked',
    });
    expect(shelfLabel({ owned: false, product_status: status('unavailable'), free_chapter: null })).toEqual({
      text: 'در دسترس نیست',
      kind: 'locked',
    });
    expect(shelfLabel({ owned: false, product_status: status('paid'), free_chapter: null })).toEqual({
      text: 'نسخه‌ی کامل',
      kind: 'locked',
    });
  });
});
