"""Отфильтровать dedup-план: оставить только безопасные слияния.

Оставляем merge-рёбра:
  - method == 'llm'    и merge == True  (семантика подтверждена LLM);
  - method == 'expert' и merge == True  (фамилия + совместимые инициалы);
  - method в auto_*    и merge == True, НО только если пара различается
    исключительно регистром (name_a.casefold() == name_b.casefold()).

Все остальные auto_cosine/auto_fuzzy-слияния (реальные текстовые различия:
сульфат/сульфит/сульфид, Ca/CaO, вход/выход, P80 145/150, шлак/шлам и т.п.)
отбрасываются, чтобы не портить числовые факты в графе.

Кластеры пересобираются union-find'ом ТОЛЬКО из оставшихся рёбер, поэтому
транзитивно склеенные ранее узлы больше не сливаются через рискованное ребро.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from app.graph.convert import ENTITY_LABELS
from app.graph.dedup import (
    PairDecision,
    build_merge_clusters,
    fetch_entities,
    write_plan,
)
from app.graph.driver import close_driver, get_driver

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTO_METHODS = {"auto_cosine", "auto_fuzzy"}


def is_safe_merge(dec: dict) -> bool:
    """True, если это merge-ребро можно безопасно применить."""
    if not dec.get("merge"):
        return False
    method = dec.get("method")
    if method in {"llm", "expert"}:
        return True
    if method in AUTO_METHODS:
        a = str(dec.get("name_a", ""))
        b = str(dec.get("name_b", ""))
        return a.casefold() == b.casefold()
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Фильтр dedup-плана")
    parser.add_argument("--in", dest="in_path", type=Path,
                        default=REPO_ROOT / "data" / "dedup_plan.json")
    parser.add_argument("--out", dest="out_path", type=Path,
                        default=REPO_ROOT / "data" / "dedup_plan_filtered.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    data = json.loads(args.in_path.read_text(encoding="utf-8"))
    raw_decisions = data.get("decisions") or []

    kept_by_label: dict[str, list[PairDecision]] = {}
    dropped = 0
    kept = 0
    for d in raw_decisions:
        d = dict(d)
        if d.get("merge") and not is_safe_merge(d):
            d["merge"] = False
            d["canon_id"] = None
            d["canon_name_norm"] = None
            dropped += 1
        elif d.get("merge"):
            kept += 1
        dec = PairDecision(**d)
        kept_by_label.setdefault(dec.label, []).append(dec)

    logger.info("Оставлено безопасных merge-рёбер: %d; отброшено рискованных: %d", kept, dropped)

    driver = get_driver()
    try:
        all_decisions: list[PairDecision] = []
        all_clusters = []
        for label in ENTITY_LABELS:
            decisions = kept_by_label.get(label, [])
            if not decisions:
                continue
            nodes = fetch_entities(driver, label)
            clusters = build_merge_clusters(label, nodes, decisions)
            all_decisions.extend(decisions)
            all_clusters.extend(clusters)

        write_plan(
            all_decisions,
            all_clusters,
            dry_run=True,
            path=args.out_path,
            source=f"filtered:{args.in_path.name}",
        )
        nodes_to_merge = sum(len(c.duplicates) for c in all_clusters)
        print(
            f"\n[ФИЛЬТР] кластеров: {len(all_clusters)}, "
            f"узлов к слиянию: {nodes_to_merge} "
            f"(было отброшено рискованных рёбер: {dropped})"
        )
    finally:
        close_driver()
    return 0


if __name__ == "__main__":
    sys.exit(main())
