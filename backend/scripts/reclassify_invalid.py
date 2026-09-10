"""重分类：把 custom_field_32 中"非分类内容"(如 重复需求 / 报表- / 11 等) 的需求，
用 AI 模块分类逻辑重新分类并写回正确的 一级-二级 值。

- 目标来自 scripts/inspect_field_values.json 的 invalid_ids（仅这 62 条，与旧批量任务的 ID 集不重叠）。
- 幂等：处理前再校验一次，若已是合法分类值则跳过。
- 仅写回 custom_field_32，不动其他字段。

用法:
  PYTHONPATH=. .venv/Scripts/python.exe scripts/reclassify_invalid.py
"""
import asyncio
import json
import os
from datetime import datetime

from app.config import settings
from app.tapd_client import tapd_client, TAPDClientError
from app.classifier import _classify_with_llm
from app.classification_kb import CATEGORY_TREE

REPORT_PATH = os.path.join(os.path.dirname(__file__), "reclassify_report.jsonl")
INSPECT_JSON = os.path.join(os.path.dirname(__file__), "inspect_field_values.json")


def is_valid_module_value(v: str) -> bool:
    v = (v or "").strip()
    if not v:
        return False
    if "-" in v:
        l1, l2 = v.split("-", 1)
        l1, l2 = l1.strip(), l2.strip()
        return l1 in CATEGORY_TREE and l2 in CATEGORY_TREE.get(l1, [])
    return v in CATEGORY_TREE


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def main():
    ws = settings.tapd_workspace_ids.split(",")[0].strip()
    field = settings.custom_field_ai_module

    with open(INSPECT_JSON, encoding="utf-8") as f:
        inspect = json.load(f)
    targets = inspect.get("invalid_ids", [])
    print(f"[{_ts()}] 待重分类目标数: {len(targets)}  (field={field})")

    # 一次性拉取全部需求，构建 id -> story 映射（含 description）
    print(f"[{_ts()}] 拉取全部需求用于取描述...")
    stories = await tapd_client.get_stories_all(workspace_id=ws, limit_per_page=200, max_pages=300)
    story_map = {}
    for it in stories:
        s = it.get("Story", it) if isinstance(it, dict) else {}
        story_map[s.get("id", "")] = s
    print(f"[{_ts()}] 已建立 {len(story_map)} 条需求的映射")

    written = skipped = failed = 0
    with open(REPORT_PATH, "a", encoding="utf-8") as f_report:
        for i, t in enumerate(targets, 1):
            sid = t["id"]
            old_val = t.get("value", "")
            s = story_map.get(sid, {})
            title = s.get("name", "") or t.get("name", "")
            description = s.get("description", "") or ""

            # 再校验一次：若字段已被改成合法值（例如别的进程改过），跳过
            cur = (s.get(field) or "").strip()
            if is_valid_module_value(cur):
                rec = {"time": _ts(), "story_id": sid, "status": "skip_valid", "old": old_val, "new": cur}
                f_report.write(json.dumps(rec, ensure_ascii=False) + "\n"); f_report.flush()
                skipped += 1
                print(f"[{i}/{len(targets)}] skip(已是合法值): {sid} -> {cur}")
                continue

            try:
                r = await _classify_with_llm(title, description, images=None)
                l1 = r.get("category_l1", "")
                l2 = r.get("category_l2", "")
                if l1 in ("其它", "其他"):
                    l1 = "对接"
                new_val = f"{l1}-{l2}" if l2 else l1
                await tapd_client.update_story_custom_fields(ws, sid, {field: new_val})
                rec = {"time": _ts(), "story_id": sid, "status": "written",
                       "old": old_val, "new": new_val, "l1": l1, "l2": l2}
                written += 1
                print(f"[{i}/{len(targets)}] {sid}: {old_val!r} -> {new_val!r}  ({title[:30]})")
            except TAPDClientError as e:
                rec = {"time": _ts(), "story_id": sid, "status": "tapd_error", "old": old_val, "error": str(e)[:200]}
                failed += 1
                print(f"[{i}/{len(targets)}] tapd_error {sid}: {str(e)[:80]}")
            except Exception as e:
                rec = {"time": _ts(), "story_id": sid, "status": "llm_error", "old": old_val, "error": str(e)[:200]}
                failed += 1
                print(f"[{i}/{len(targets)}] llm_error {sid}: {str(e)[:80]}")
            f_report.write(json.dumps(rec, ensure_ascii=False) + "\n"); f_report.flush()
            await asyncio.sleep(0.3)

    print(f"\n[{_ts()}] 完成。写回 {written}，跳过(已合法) {skipped}，失败 {failed}。报告见 {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
