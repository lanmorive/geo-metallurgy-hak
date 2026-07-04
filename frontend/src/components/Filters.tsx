import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import type { NumericFilter, NumericOperator, QueryFilters } from '../api/client'
import { defaultFilters, filtersEqual } from '../constants/defaultFilters'

interface FiltersProps {
  filters: QueryFilters
  onChange: (filters: QueryFilters) => void
  onReset: () => void
}

type GeoOption = 'RU' | 'WORLD' | 'ALL'

const GEO_OPTIONS: { value: GeoOption; label: string }[] = [
  { value: 'RU', label: 'RU' },
  { value: 'WORLD', label: 'Мир' },
  { value: 'ALL', label: 'Все' },
]

const OPERATORS: { value: NumericOperator; label: string }[] = [
  { value: '<=', label: '≤' },
  { value: '>=', label: '≥' },
  { value: '=', label: '=' },
  { value: 'range', label: 'диапазон' },
]

const INVALID_NUMERIC_CLASS = 'border-red-500 focus:border-red-500'
const VALID_INPUT_CLASS =
  'border-surface-border focus:outline-none focus:border-brand-primary'

function formatNumericFilter(f: NumericFilter): string {
  const unit = f.unit ? ` ${f.unit}` : ''
  if (f.operator === 'range' && f.value_max != null) {
    return `${f.value}–${f.value_max}${unit}`
  }
  const op = f.operator === '<=' ? '≤' : f.operator === '>=' ? '≥' : '='
  return `${op} ${f.value}${unit}`
}

function geoToOption(geo: string | null | undefined): GeoOption {
  if (geo === 'RU') return 'RU'
  if (geo === 'WORLD') return 'WORLD'
  return 'ALL'
}

function isInvalidNumberInput(value: string): boolean {
  return value !== '' && !Number.isFinite(Number(value))
}

export default function Filters({ filters, onChange, onReset }: FiltersProps) {
  const yearFrom = filters.year_range?.[0] ?? 2010
  const yearTo = filters.year_range?.[1] ?? 2026
  const minConfidence = filters.min_confidence ?? 0
  const numericFilters = filters.numeric_filters ?? []
  const isDirty = !filtersEqual(filters, defaultFilters)

  const [showAddForm, setShowAddForm] = useState(false)
  const [newParam, setNewParam] = useState('')
  const [newOperator, setNewOperator] = useState<NumericOperator>('range')
  const [newValue, setNewValue] = useState('')
  const [newValueMax, setNewValueMax] = useState('')
  const [newUnit, setNewUnit] = useState('')

  const geoOption = geoToOption(filters.geo)

  const yearFromInvalid = !Number.isFinite(yearFrom)
  const yearToInvalid = !Number.isFinite(yearTo)
  const newValueInvalid = isInvalidNumberInput(newValue)
  const newValueMaxInvalid = newOperator === 'range' && isInvalidNumberInput(newValueMax)

  const canAddNumeric =
    newParam.trim() !== '' &&
    newValue !== '' &&
    !newValueInvalid &&
    (newOperator !== 'range' || (newValueMax !== '' && !newValueMaxInvalid))

  const handleGeoChange = (option: GeoOption) => {
    onChange({
      ...filters,
      geo: option === 'ALL' ? null : option,
    })
  }

  const removeNumericFilter = (index: number) => {
    onChange({
      ...filters,
      numeric_filters: numericFilters.filter((_, i) => i !== index),
    })
  }

  const addNumericFilter = () => {
    if (!canAddNumeric) return

    const value = Number(newValue)
    const filter: NumericFilter = {
      parameter: newParam.trim(),
      operator: newOperator,
      value,
      unit: newUnit.trim() || null,
    }
    if (newOperator === 'range') {
      filter.value_max = Number(newValueMax)
    }

    onChange({
      ...filters,
      numeric_filters: [...numericFilters, filter],
    })
    setNewParam('')
    setNewOperator('range')
    setNewValue('')
    setNewValueMax('')
    setNewUnit('')
    setShowAddForm(false)
  }

  return (
    <div className="flex flex-col gap-5 p-4 overflow-y-auto h-full">
      <section>
        <h3 className="text-xs text-neutral-500 mb-2">География</h3>
        <div className="flex gap-1">
          {GEO_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => handleGeoChange(opt.value)}
              className={`px-3 py-1 text-xs rounded-pill border transition-colors ${
                geoOption === opt.value
                  ? 'bg-brand-primary text-white border-brand-primary'
                  : 'bg-surface-card text-neutral-700 border-surface-border hover:bg-neutral-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-xs text-neutral-500 mb-2">Годы</h3>
        <div className="flex items-center gap-2">
          <input
            type="number"
            value={yearFromInvalid ? '' : yearFrom}
            onChange={(e) =>
              onChange({
                ...filters,
                year_range: [Number(e.target.value), yearTo],
              })
            }
            title={yearFromInvalid ? 'Введите число' : undefined}
            className={`w-full font-mono text-sm rounded-control border bg-surface-card px-2 py-1.5 ${
              yearFromInvalid ? INVALID_NUMERIC_CLASS : VALID_INPUT_CLASS
            }`}
          />
          <span className="text-neutral-400 text-sm">–</span>
          <input
            type="number"
            value={yearToInvalid ? '' : yearTo}
            onChange={(e) =>
              onChange({
                ...filters,
                year_range: [yearFrom, Number(e.target.value)],
              })
            }
            title={yearToInvalid ? 'Введите число' : undefined}
            className={`w-full font-mono text-sm rounded-control border bg-surface-card px-2 py-1.5 ${
              yearToInvalid ? INVALID_NUMERIC_CLASS : VALID_INPUT_CLASS
            }`}
          />
        </div>
      </section>

      <section>
        <h3 className="text-xs text-neutral-500 mb-2">
          Достоверность ≥{' '}
          <span className="font-mono">{minConfidence.toFixed(2)}</span>
        </h3>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={minConfidence}
          onChange={(e) =>
            onChange({ ...filters, min_confidence: Number(e.target.value) })
          }
          className="w-full accent-brand-primary"
        />
      </section>

      <section>
        <h3 className="text-xs text-neutral-500 mb-1">Параметры</h3>
        <p className="text-[11px] text-neutral-400 mb-2">
          Необязательно: условия можно писать прямо в вопросе — система поймёт числа и диапазоны
        </p>
        <div className="space-y-2">
          {numericFilters.map((f, i) => (
            <div
              key={`${f.parameter}-${i}`}
              className="flex items-start justify-between gap-2 rounded-card border border-surface-border bg-surface-card p-3"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium capitalize">{f.parameter}</div>
                <div className="text-xs font-mono text-neutral-600 mt-0.5">
                  {formatNumericFilter(f)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => removeNumericFilter(i)}
                className="shrink-0 p-1 text-neutral-400 hover:text-neutral-700 rounded-control"
                aria-label="Удалить параметр"
              >
                <X size={14} />
              </button>
            </div>
          ))}

          {showAddForm ? (
            <div className="rounded-card border border-surface-border bg-surface-card p-3 space-y-2">
              <input
                type="text"
                placeholder="Параметр"
                value={newParam}
                onChange={(e) => setNewParam(e.target.value)}
                className={`w-full text-sm rounded-control border px-2 py-1.5 ${VALID_INPUT_CLASS}`}
              />
              <select
                value={newOperator}
                onChange={(e) => setNewOperator(e.target.value as NumericOperator)}
                className={`w-full text-sm rounded-control border px-2 py-1.5 ${VALID_INPUT_CLASS}`}
              >
                {OPERATORS.map((op) => (
                  <option key={op.value} value={op.value}>
                    {op.label}
                  </option>
                ))}
              </select>
              <div className="flex gap-2">
                <input
                  type="number"
                  placeholder="Значение"
                  value={newValue}
                  onChange={(e) => setNewValue(e.target.value)}
                  title={newValueInvalid ? 'Введите число' : undefined}
                  className={`flex-1 font-mono text-sm rounded-control border px-2 py-1.5 ${
                    newValueInvalid ? INVALID_NUMERIC_CLASS : VALID_INPUT_CLASS
                  }`}
                />
                {newOperator === 'range' && (
                  <input
                    type="number"
                    placeholder="До"
                    value={newValueMax}
                    onChange={(e) => setNewValueMax(e.target.value)}
                    title={newValueMaxInvalid ? 'Введите число' : undefined}
                    className={`flex-1 font-mono text-sm rounded-control border px-2 py-1.5 ${
                      newValueMaxInvalid ? INVALID_NUMERIC_CLASS : VALID_INPUT_CLASS
                    }`}
                  />
                )}
              </div>
              <input
                type="text"
                placeholder="Единица"
                value={newUnit}
                onChange={(e) => setNewUnit(e.target.value)}
                className={`w-full font-mono text-sm rounded-control border px-2 py-1.5 ${VALID_INPUT_CLASS}`}
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={addNumericFilter}
                  disabled={!canAddNumeric}
                  className="flex-1 text-xs py-1.5 rounded-control bg-brand-primary text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Добавить
                </button>
                <button
                  type="button"
                  onClick={() => setShowAddForm(false)}
                  className="flex-1 text-xs py-1.5 rounded-control border border-surface-border text-neutral-600 hover:bg-neutral-50"
                >
                  Отмена
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setShowAddForm(true)}
              className="w-full flex items-center justify-center gap-1 text-xs py-2 rounded-control border border-dashed border-surface-border text-neutral-500 hover:bg-neutral-50 hover:text-neutral-700"
            >
              <Plus size={14} />
              Добавить параметр
            </button>
          )}
        </div>
      </section>

      {isDirty && (
        <button
          type="button"
          onClick={onReset}
          className="text-xs py-2 rounded-control border border-surface-border text-neutral-600 hover:bg-neutral-50"
        >
          Сбросить фильтры
        </button>
      )}
    </div>
  )
}
