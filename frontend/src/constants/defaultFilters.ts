import type { NumericFilter, QueryFilters } from '../api/client'

export const defaultFilters: QueryFilters = {
  geo: 'RU',
  year_range: [2010, 2026],
  min_confidence: 0.6,
  numeric_filters: [
    { parameter: 'сульфаты', operator: 'range', value: 200, value_max: 300, unit: 'мг/л' },
    { parameter: 'сухой остаток', operator: '<=', value: 1000, unit: 'мг/дм³' },
  ],
}

function numericFilterEqual(a: NumericFilter, b: NumericFilter): boolean {
  return (
    a.parameter === b.parameter &&
    a.operator === b.operator &&
    a.value === b.value &&
    a.value_max === b.value_max &&
    a.unit === b.unit
  )
}

export function filtersEqual(a: QueryFilters, b: QueryFilters): boolean {
  if (a.geo !== b.geo) return false
  if (a.min_confidence !== b.min_confidence) return false

  const aYears = a.year_range ?? null
  const bYears = b.year_range ?? null
  if (aYears?.[0] !== bYears?.[0] || aYears?.[1] !== bYears?.[1]) return false

  const aNumeric = a.numeric_filters ?? []
  const bNumeric = b.numeric_filters ?? []
  if (aNumeric.length !== bNumeric.length) return false
  return aNumeric.every((f, i) => numericFilterEqual(f, bNumeric[i]))
}
