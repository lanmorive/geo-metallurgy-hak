# Онтология графа знаний — v2 (после разбора реального корпуса)

Кодовое воплощение — `backend/app/schemas/ontology.py`.
ЛЮБОЕ изменение здесь = изменение в schemas + типах фронта + промптах
extraction. После Ч+2 менять только с согласия всей команды.

Изменения v2: добавлены `Organization` и `Chunk`; `Publication` получила
библиографические атрибуты (year, lang, doc_type, venue); добавлены связи
AFFILIATED_WITH, OWNS, OPERATES, PART_OF. Принцип разделения:
**нода — то, через что ходят запросы; свойство — то, чем фильтруют.**

## Типы сущностей (узлы Neo4j, label = тип)

| Тип | Описание | Ключевые атрибуты |
|---|---|---|
| `Material` | Материал, руда, реагент, сплав, концентрат | name, formula?, class |
| `Process` | Технологический процесс (флотация, выщелачивание, RKEF) | name, category |
| `Equipment` | Оборудование (электропечь, вращающаяся печь, конвертер) | name, model?, vendor? |
| `Property` | Свойство/параметр (содержание Ni, влажность, извлечение) | name, unit? |
| `Experiment` | Эксперимент/испытание/лабораторная стадия | title, date?, scale (lab/pilot/industrial) |
| `Publication` | Документ-источник: статья, отчёт, справка, доклад, презентация | title, **year**, **lang** (ru/en), **doc_type** (report/article/presentation/reference), **venue?** (журнал/издание, строка), source_path |
| `Chunk` | Фрагмент текста публикации (носитель эмбеддинга) | text, embedding (vector 1024), chunk_index |
| `Expert` | Исследователь, автор, руководитель работ | name |
| `Organization` | Компания, институт, СП (Норникель, Гипроникель, Cunico, Vale) | name, org_type (company/institute/JV), country? |
| `Facility` | Завод, рудник, установка, месторождение (FENI Kavadarchi, Drenas) | name, facility_type (plant/mine/deposit/lab), location? |

Общие атрибуты каждого узла: `id` (uuid), `name`, `name_norm`
(канонический термин после normalizer), `aliases` (синонимы RU/EN).

## Что НЕ ноды (осознанно — фильтры, не хабы навигации)
- Год, язык, тип документа, география — свойства (иначе supernodes)
- Название журнала/издания — строка `venue` на Publication (в корпусе
  почти нет журналов; продвижение до ноды — один Cypher-скрипт, если
  понадобится)

## Типы связей (рёбра)

| Связь | От → К | Смысл |
|---|---|---|
| `uses_material` | Experiment/Process/Facility → Material | использует материал/сырьё |
| `operates_at_condition` | Experiment/Process → Property | режим; числовое ограничение на ребре |
| `produces_output` | Experiment/Process/Facility → Material/Property | результат/продукция |
| `described_in` | любая → Publication | источник факта |
| `validated_by` | утверждение → Experiment | подтверждено экспериментом |
| `contradicts` | Publication/Experiment ↔ Publication/Experiment | источники противоречат |
| `authored_by` | Publication/Experiment → Expert | авторство |
| `affiliated_with` | Expert → Organization | аффилиация («какие команды занимались X») |
| `owns` | Organization → Facility/Organization | владение активом (Cunico owns FENI) |
| `operates` | Organization → Facility | эксплуатация |
| `conducted_at` | Experiment → Facility | место проведения |
| `uses_equipment` | Experiment/Process/Facility → Equipment | использует оборудование |
| `part_of` | Chunk → Publication | фрагмент документа |
| `relates_to` | любая → любая | слабая тематическая связь (fallback, confidence ≤ 0.5) |

## Числовые ограничения (NumericConstraint)
Атрибуты на ребре `operates_at_condition` либо на Property:

```
parameter: str      # "сульфаты", "содержание Ni", "влажность"
operator:  str      # "<=", ">=", "=", "range"
value:     float    # 300.0; для range: value_min, value_max
unit:      str      # "мг/л", "%", "тыс т/г"
```

Правила: единицы хранить КАК В ИСТОЧНИКЕ (эквивалентность решает
normalizer, не extraction). Никаких молчаливых конвертаций и округлений.
Диапазоны из таблиц спецификаций («Ni 17-25%») — operator="range",
value_min=17, value_max=25, unit="%".

## Метаданные (два разных слоя — не путать!)

**Библиография** — живёт ОДИН раз: атрибуты на `Publication`
(year, lang, doc_type, venue) + ноды `Expert`/`Organization` через
authored_by / affiliated_with.

**Провенанс** — ДУБЛИРУЕТСЯ на каждом извлечённом узле-факте и ребре,
отвечает «откуда мы знаем именно этот факт»:

```
source_doc: str     # путь/id документа-источника
confidence: float   # 0..1 от LLM; -0.2 если факт прошёл retry
geography:  str     # "RU" | "WORLD" | ISO-код | "UNKNOWN"
year:       int?    # год источника (денормализация для фильтров)
```

## Нормализация терминов
`extraction/normalizer.py`: словарь синонимов RU↔EN, ОБЯЗАТЕЛЕН —
корпус двуязычный ("ферроникель" ≡ "ferronickel", "выщелачивание" ≡
"leaching", "вращающаяся печь" ≡ "rotary kiln"). `name_norm` —
канонический термин (русский); по нему uniqueness constraint → дубли
мержатся при MERGE-загрузке. Варианты имён людей ("Евграфова А.К." /
"А. Евграфова") нормализуются к "Фамилия И.О.".

## Особенности корпуса (влияют на extraction)
- Таблицы спецификаций — концентрат фактов (составы руд, FeNi 17-25% Ni);
  парсер обязан сохранять таблицы, extraction — обрабатывать их отдельным
  промптом
- Организации и активы (кто кем владеет, кто что купил) — значимая часть
  «клубка»: извлекать owns/operates с датами в атрибутах ребра
- Типы документов: отчёты, справки, доклады, презентации, EN-обзоры

## Индексы Neo4j (graph/schema.cypher)
- UNIQUE constraint: (label, name_norm) для всех label кроме Chunk
- Fulltext index по name + aliases всех label
- Vector index по Chunk.embedding (bge-m3, 1024 dim, cosine)