"""批量执行：对 2026.7.1~2026.9.30 创建、且 AI模块分类字段(custom_field_ai_module)为空的需求，
执行 AI 模块分类并写回 TAPD 预设字段。

特性：
- 幂等：每处理前检查 TAPD 字段是否已非空，已填则跳过（支持断点续跑：中断后重跑自动跳过已写回的）。
- 进度持久化：每完成一条即追加一行到 classify_run_report.jsonl（含 l1/l2/状态/错误）。
- 限速与容错：逐条串行，调用间 0.3s 间隔；单条失败计入报告并继续。
- 仅写回 custom_field_ai_module 字段，不写评论、不改处理人。

用法:
  PYTHONPATH=. .venv/Scripts/python.exe scripts/classify_date_range_run.py [--limit N] [--dry-run]
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

from app.config import settings
from app.tapd_client import tapd_client, TAPDClientError
from app.classifier import _classify_with_llm

REPORT_PATH = os.path.join(os.path.dirname(__file__), "classify_run_report.jsonl")


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def process_story(story, field, f_report):
    s = story.get("Story", story) if isinstance(story, dict) else {}
    story_id = s.get("id", "")
    title = s.get("name", "")
    description = s.get("description", "") or ""
    ws = s.get("workspace_id", "") or settings.tapd_workspace_ids.split(",")[0].strip()

    try:
        result = await _classify_with_llm(title, description, images=None)
        l1 = result.get("category_l1", "")
        l2 = result.get("category_l2", "")
        if l1 in ("其它", "其他"):
            l1 = "对接"
        module_value = f"{l1}-{l2}" if l2 else l1

        await tapd_client.update_story_custom_fields(
            workspace_id=ws,
            story_id=story_id,
            fields={field: module_value},
        )
        rec = {"time": _ts(), "story_id": story_id, "status": "written",
               "l1": l1, "l2": l2, "value": module_value}
        print(f"[written] {story_id} -> {module_value}  ({title[:36]})")
    except TAPDClientError as e:
        rec = {"time": _ts(), "story_id": story_id, "status": "tapd_error",
               "error": str(e)[:200]}
        print(f"[tapd_error] {story_id}: {str(e)[:100]}")
    except Exception as e:
        rec = {"time": _ts(), "story_id": story_id, "status": "llm_error",
               "error": str(e)[:200]}
        print(f"[llm_error] {story_id}: {str(e)[:100]}")

    f_report.write(json.dumps(rec, ensure_ascii=False) + "\n")
    f_report.flush()
    return rec


async def main(limit: int, dry_run: bool):
    ws = settings.tapd_workspace_ids.split(",")[0].strip()
    field = settings.custom_field_ai_module
    print(f"[{_ts()}] workspace={ws}  AI模块分类字段={field}  dry_run={dry_run}  limit={limit or '全部'}")

    lo = datetime(2026, 7, 1, 0, 0, 0)
    hi = datetime(2026, 9, 30, 23, 59, 59)

    print(f"[{_ts()}] 拉取全部需求（分页，max_pages=300）...")
    stories = await tapd_client.get_stories_all(workspace_id=ws, limit_per_page=200, max_pages=300)
    print(f"[{_ts()}] 共拉取 {len(stories)} 条")

    # 过滤时间范围 + 字段为空
    targets = []
    skipped_nonempty = 0
    for item in stories:
        s = item.get("Story", item) if isinstance(item, dict) else {}
        created_raw = s.get("created", "")
        try:
            created = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S") if created_raw else None
        except Exception:
            created = None
        if created is None or not (lo <= created <= hi):
            continue
        val = s.get(field, "") or ""
        val = (val.strip() if isinstance(val, str) else str(val).strip())
        if val:
            skipped_nonempty += 1
            continue
        targets.append(item)

    print(f"[{_ts()}] 时间范围内 {len(targets) + skipped_nonempty} 条；字段已填跳过 {skipped_nonempty}；待分类 {len(targets)} 条")

    if limit:
        targets = targets[:limit]
        print(f"[{_ts()}] 受 --limit 限制，本次处理前 {len(targets)} 条")

    if dry_run:
        print(f"[{_ts()}] DRY-RUN 结束，未写回任何数据。")
        for it in targets[:10]:
            s = it.get("Story", it)
            print("  ", s.get("created"), s.get("id"), (s.get("name", "")[:40]))
        return

    written = failed = 0
    with open(REPORT_PATH, "a", encoding="utf-8") as f_report:
        for idx, item in enumerate(targets, 1):
            s = item.get("Story", item) if isinstance(item, dict) else {}
            sid = s.get("id", "")
            print(f"[{_ts()}] ({idx}/{len(targets)}) 处理 {sid}", end="  ", flush=True)
            rec = await process_story(item, field, f_report)
            if rec["status"] == "written":
                written += 1
            else:
                failed += 1
            await asyncio.sleep(0.3)

    print(f"\n[{_ts()}] 完成。写回成功 {written}，失败 {failed}。报告见 {REPORT_PATH}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="本次最多处理条数(0=全部)")
    p.add_argument("--dry-run", action="store_true", help="只统计不写回")
    args = p.parse_args()
    asyncio.run(main(args.limit, args.dry_run))
