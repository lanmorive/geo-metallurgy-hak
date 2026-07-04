import type { NumericFilter, QueryFilters } from '../api/client'

function isValidNumericFilter(f: NumericFilter): boolean {
  if (f.value != null && !Number.isFinite(f.value)) return false
  if (f.operator === 'range') {
    if (f.value_max == null || !Number.isFinite(f.value_max)) return false
  }
  return f.value != null && Number.isFinite(f.value)
}

export function sanitizeFilters(filters: QueryFilters): QueryFilters {
  const result: QueryFilters = {
    geo: filters.geo,
    min_confidence: filters.min_confidence,
  }

  const [from, to] = filters.year_range ?? []
  if (Number.isFinite(from) && Number.isFinite(to)) {
    result.year_range = [from as number, to as number]
  }

  const numeric = (filters.numeric_filters ?? []).filter(isValidNumericFilter)
  if (numeric.length > 0) {
    result.numeric_filters = numeric
  }

  return result
}
