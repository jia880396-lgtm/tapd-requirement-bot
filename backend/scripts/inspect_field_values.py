"""只读排查：统计 2026.7.1~2026.9.30 范围内需求 custom_field_32 (AI模块分类) 的所有取值，
对照有效分类树标记出“非分类内容”，并输出需重分类的需求 ID。

用法:
  PYTHONPATH=. .venv/Scripts/python.exe scripts/inspect_field_values.py
"""
import asyncio
import json
from collections import Counter, defaultdict
from datetime import datetime

from app.config import settings
from app.tapd_client import tapd_client
from app.classification_kb import CATEGORY_TREE

REPORT_PATH = "scripts/inspect_field_values.json"


def is_valid_module_value(v: str) -> bool:
    v = (v or "").strip()
    if not v:
        return False
    if "-" in v:
        l1, l2 = v.split("-", 1)
        l1, l2 = l1.strip(), l2.strip()
        return l1 in CATEGORY_TREE and l2 in CATEGORY_TREE.get(l1, [])
    else:
        return v in CATEGORY_TREE


async def main():
    ws = settings.tapd_workspace_ids.split(",")[0].strip()
    field = settings.custom_field_ai_module
    print(f"[{datetime.now():%H:%M:%S}] workspace={ws} field={field}")
    print(f"[{datetime.now():%H:%M:%S}] 拉取全部需求(max_pages=300)...")
    stories = await tapd_client.get_stories_all(workspace_id=ws, limit_per_page=200, max_pages=300)
    print(f"[{datetime.now():%H:%M:%S}] 共拉取 {len(stories)} 条")

    lo = datetime(2026, 7, 1, 0, 0, 0)
    hi = datetime(2026, 9, 30, 23, 59, 59)

    in_range = 0
    nonempty = 0
    value_counter = Counter()
    invalid_ids = []        # 字段非空但非合法分类值
    empty_ids = []          # 字段为空(正常待分类, 由批量脚本处理)
    valid_ids = []          # 字段为合法分类值

    for item in stories:
        s = item.get("Story", item) if isinstance(item, dict) else {}
        created_raw = s.get("created", "")
        try:
            created = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S") if created_raw else None
        except Exception:
            created = None
        if created is None or not (lo <= created <= hi):
            continue
        in_range += 1
        val = (s.get(field) or "").strip()
        if not val:
            empty_ids.append(s.get("id", ""))
            continue
        nonempty += 1
        value_counter[val] += 1
        if is_valid_module_value(val):
            valid_ids.append(s.get("id", ""))
        else:
            invalid_ids.append({"id": s.get("id", ""), "value": val, "name": s.get("name", "")})

    print(f"\n=== 统计 ===")
    print(f"时间范围内需求总数      : {in_range}")
    print(f"字段非空(已填)          : {nonempty}")
    print(f"  其中合法分类值        : {len(valid_ids)}")
    print(f"  其中非分类内容(待重分): {len(invalid_ids)}")
    print(f"字段为空(正常待分类)    : {len(empty_ids)}")

    print(f"\n=== 所有非空字段取值(按出现次数) ===")
    for v, c in value_counter.most_common():
        tag = "OK" if is_valid_module_value(v) else "<<< 非分类"
        print(f"  {c:5d}  {v!r:40s} {tag}")

    print(f"\n=== 非分类内容样例(前 20 条) ===")
    for r in invalid_ids[:20]:
        print(f"  {r['id']}  value={r['value']!r}  name={r['name'][:40]}")

    out = {
        "in_range": in_range,
        "nonempty": nonempty,
        "valid": len(valid_ids),
        "invalid": len(invalid_ids),
        "empty": len(empty_ids),
        "distinct_values": dict(value_counter.most_common()),
        "invalid_ids": invalid_ids,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n明细已写入 {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
