import type { Item } from './api'

/** Grid rows hold numbers (the API sends money as strings) so editing, sorting and sums work. */
export type Row = Omit<Item, 'unit_price' | 'price_low' | 'price_high' | 'total_value'> & {
  unit_price: number | null
  price_low: number | null
  price_high: number | null
}

export const toRow = (item: Item): Row => ({
  ...item,
  unit_price: item.unit_price === null ? null : Number(item.unit_price),
  price_low: item.price_low === null ? null : Number(item.price_low),
  price_high: item.price_high === null ? null : Number(item.price_high),
})
