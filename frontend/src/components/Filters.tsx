import type { QueryFilters } from '../api/client'

interface FiltersProps {
  filters: QueryFilters
  onChange: (filters: QueryFilters) => void
}

export default function Filters({ filters, onChange }: FiltersProps) {
  const yearFrom = filters.year_range?.[0] ?? 2010
  const yearTo = filters.year_range?.[1] ?? 2025
  const minConfidence = filters.min_confidence ?? 0

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-cyan-300">Фильтры</h2>

      <label className="block text-sm">
        <span className="text-slate-400">География</span>
        <select
          value={filters.geo ?? ''}
          onChange={(e) => onChange({ ...filters, geo: e.target.value || null })}
          className="mt-1 w-full rounded bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm"
        >
          <option value="">Все</option>
          <option value="RU">Россия</option>
          <option value="WORLD">Мир</option>
        </select>
      </label>

      <label className="block text-sm">
        <span className="text-slate-400">Год от</span>
        <input
          type="number"
          value={yearFrom}
          onChange={(e) =>
            onChange({
              ...filters,
              year_range: [Number(e.target.value), yearTo],
            })
          }
          className="mt-1 w-full rounded bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm"
        />
      </label>

      <label className="block text-sm">
        <span className="text-slate-400">Год до</span>
        <input
          type="number"
          value={yearTo}
          onChange={(e) =>
            onChange({
              ...filters,
              year_range: [yearFrom, Number(e.target.value)],
            })
          }
          className="mt-1 w-full rounded bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm"
        />
      </label>

      <label className="block text-sm">
        <span className="text-slate-400">
          Мин. confidence: {minConfidence.toFixed(2)}
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={minConfidence}
          onChange={(e) =>
            onChange({ ...filters, min_confidence: Number(e.target.value) })
          }
          className="mt-1 w-full"
        />
      </label>

      <div className="text-xs text-slate-500 border-t border-slate-700 pt-3">
        Числовые фильтры (сульфаты, TDS) — через text2cypher на бэкенде
      </div>
    </div>
  )
}
