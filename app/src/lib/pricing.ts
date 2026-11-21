import type { PriceDiscount, ProductStatus } from '../api/endpoints';
import { toPersianDigits } from '../theme';

export type PricedItem = {
  price: number | null;
  regular_price?: number | null;
  discount?: PriceDiscount | null;
  product_status: ProductStatus;
};

export function currentPrice(item: PricedItem, now = Date.now()) {
  const regularPrice = item.regular_price ?? item.price;
  const discount = item.discount ?? null;
  const withinCampaign = !!discount && Number.isFinite(Date.parse(discount.ends_at)) && Date.parse(discount.ends_at) > now && Date.parse(discount.starts_at) <= now;
  const active = item.product_status.promotion === 'discount' && withinCampaign;
  const price = active ? item.price : regularPrice;
  return {
    price,
    regularPrice,
    discount: active && price != null && regularPrice != null && price < regularPrice ? discount : null,
  };
}

export function percentLabel(percent: number): string {
  const text = Number.isInteger(percent) ? String(percent) : percent.toFixed(1).replace('.', '٫');
  return toPersianDigits(text);
}
