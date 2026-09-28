from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

data = json.loads(Path("_tmp_kpi_ship_share.json").read_text(encoding="utf-8"))
# Recompute from saved top/focus is incomplete. Use by_dept + known numbers.

by_dept = data["by_dept"]
total = data["total"]
bmi = by_dept.get("БМИ", 0)
etalon = by_dept.get("Эталон", 0)
ved = by_dept.get("ВЭД", 0)
odp = by_dept.get("ОДП", 0)
ceh1 = by_dept.get("Производственный цех №1", 0)
ceh2 = by_dept.get("Производственный цех №2", 0)
wh = by_dept.get("Складской комплекс", 0)
other = total - bmi - etalon - ved - odp - ceh1 - ceh2 - wh
commercial = bmi + etalon + ved + odp
ext_no_ceh = total - ceh1 - ceh2
ext_no_ceh_wh = ext_no_ceh - wh
no_ceh_etalon = total - ceh1 - ceh2 - etalon
# intercompany partner from JSON
inter = 13_070_937.25
no_ceh_inter = total - ceh1 - ceh2 - inter
no_ceh_wh_inter = no_ceh_inter - wh
partner = data["partner_focus"]

slices = {
    "все реализации": (bmi, total),
    "коммерческие отделы": (bmi, commercial),
    "без цехов": (bmi, ext_no_ceh),
    "без цехов и склада": (bmi, ext_no_ceh_wh),
    "без цехов и Эталона": (bmi, no_ceh_etalon),
    "без цехов и внутренней Алмаз-НПО": (bmi, no_ceh_inter),
    "без цехов, склада и внутренней": (bmi, no_ceh_wh_inter),
    "партнёры Газпром* / все": (partner, total),
    "партнёры Газпром* / коммерция": (partner, commercial),
    "план месяца": (135_000_000 + 186_042_380, 436_108_010),
    "на 15.09 отделы": (0, data["through_15"]["total"]),
}


def pct(num, den):
    return round(100.0 * num / den, 2) if den else None

print(f"{'срез':40} {'числ.':>16} {'знам.':>16} {'доля':>8}")
for name, (n, d) in slices.items():
    print(f"{name:40} {n:16,.2f} {d:16,.2f} {pct(n,d):7.2f}%")
