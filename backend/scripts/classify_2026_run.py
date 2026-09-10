"""批量执行：对 2026 全年(1/1 ~ 截至目前)创建、且 AI模块分类字段(custom_field_ai_module)为空的需求，
执行 AI 模块分类并写回 TAPD 预设字段。

相比旧版(7.1-9.30)的优化：
- 并发执行：用 asyncio.Semaphore 控制并发度(默认 6)，LLM 调用与 TAPD 写回并发进行，大幅提速。
- 描述截断：需求 description 可能长达 1~2 万字，分类只需标题+开头，截断到 DESC_LIMIT 字符送模型。
- 失败重试：单条失败自动重试 RETRIES 次，仍失败才计入报告并跳过(不中断整体)。
- 幂等：每处理前检查 TAPD 字段是否已非空，已填则跳过（断点续跑：中断后重跑自动跳过已写回的）。
- 仅写回 custom_field_ai_module 字段，不写评论、不改处理人。

进度持久化：每完成一条即追加一行到 classify_2026_report.jsonl（含 l1/l2/状态/错误），
配合 scripts/progress_bar.py --report scripts/classify_2026_report.jsonl --total <N> 实时查看。

用法:
  PYTHONPATH=. .venv/Scripts/python.exe scripts/classify_2026_run.py [--limit N] [--dry-run] [--concurrency 6]
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

from app.config import settings
from app.tapd_client import tapd_client, TAPDClientError
from app.classifier import _classify_with_llm
import app.tapd_client as _tapd_module

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(HERE, "classify_2026_report.jsonl")

# 速度/容错参数
DESC_LIMIT = 2000        # 截断描述的最大字符数（分类只需标题+开头）
CONCURRENCY = 6          # 并发度
RETRIES = 2              # 单条失败重试次数
RETRY_BACKOFF = 2.0      # 重试间隔(秒)

# 单条硬超时：防止某次网络调用僵死（网关/TAPD 无响应且不触发底层超时）占满并发槽位导致整批停滞。
LLM_TIMEOUT = 120.0      # 单次 LLM 分类调用上限
TAPD_TIMEOUT = 45.0      # 单次 TAPD 写回上限


async def _reset_shared_tapd_client():
    """超时/报错后关闭并丢弃 TAPD 共享连接池，强制下次调用重建，避免复用僵死连接。"""
    c = _tapd_module._shared_client
    if c is not None:
        try:
            await c.aclose()
        except Exception:
            pass
        _tapd_module._shared_client = None


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def classify_one(story, field, ws, f_report, sem):
    s = story.get("Story", story) if isinstance(story, dict) else {}
    story_id = s.get("id", "")
    title = s.get("name", "")
    description = (s.get("description", "") or "")[:DESC_LIMIT]
    last_err = None
    async with sem:
        for attempt in range(RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    _classify_with_llm(title, description, images=None),
                    timeout=LLM_TIMEOUT,
                )
                l1 = result.get("category_l1", "")
                l2 = result.get("category_l2", "")
                if l1 in ("其它", "其他"):
                    l1 = "对接"
                module_value = f"{l1}-{l2}" if l2 else l1
                await asyncio.wait_for(
                    tapd_client.update_story_custom_fields(
                        workspace_id=ws, story_id=story_id, fields={field: module_value}
                    ),
                    timeout=TAPD_TIMEOUT,
                )
                rec = {"time": _ts(), "story_id": story_id, "status": "written",
                       "l1": l1, "l2": l2, "value": module_value}
                f_report.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f_report.flush()
                return rec
            except asyncio.TimeoutError:
                last_err = (f"timeout: 单条处理超时(>LLM{LLM_TIMEOUT:.0f}s/TAPD{TAPD_TIMEOUT:.0f}s，"
                            f"疑似网关或TAPD无响应)")
                await _reset_shared_tapd_client()
            except TAPDClientError as e:
                last_err = f"tapd_error: {str(e)[:180]}"
                await _reset_shared_tapd_client()
            except Exception as e:
                last_err = f"llm_error: {str(e)[:180]}"
            if attempt < RETRIES:
                await asyncio.sleep(RETRY_BACKOFF)
        # 全部重试失败
        rec = {"time": _ts(), "story_id": story_id, "status": "error", "error": last_err}
        f_report.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f_report.flush()
        return rec


async def main(limit: int, dry_run: bool, concurrency: int):
    ws = settings.tapd_workspace_ids.split(",")[0].strip()
    field = settings.custom_field_ai_module
    lo = datetime(2026, 1, 1, 0, 0, 0)
    hi = datetime.now()  # 截至目前
    sem = asyncio.Semaphore(concurrency)

    print(f"[{_ts()}] workspace={ws}  AI模块分类字段={field}  dry_run={dry_run}  limit={limit or '全部'}  concurrency={concurrency}")
    print(f"[{_ts()}] 范围: 2026-01-01 ~ {hi.strftime('%Y-%m-%d %H:%M:%S')}")

    print(f"[{_ts()}] 拉取全部需求（分页，max_pages=300）...")
    t0 = time.time()
    stories = await tapd_client.get_stories_all(workspace_id=ws, limit_per_page=200, max_pages=300)
    print(f"[{_ts()}] 共拉取 {len(stories)} 条（耗时 {time.time()-t0:.0f}s）")

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

    print(f"[{_ts()}] 范围内 {len(targets) + skipped_nonempty} 条；字段已填跳过 {skipped_nonempty}；待分类 {len(targets)} 条")

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
    t0 = time.time()
    with open(REPORT_PATH, "a", encoding="utf-8") as f_report:
        tasks = [classify_one(it, field, ws, f_report, sem) for it in targets]
        total = len(tasks)
        for done in asyncio.as_completed(tasks):
            rec = await done
            if rec["status"] == "written":
                written += 1
            else:
                failed += 1
            n = written + failed
            if n % 50 == 0 or n == total:
                el = time.time() - t0
                rate = el / n if n else 0
                print(f"[{_ts()}] 进度 {n}/{total}  成功 {written}  失败 {failed}  均速 {rate:.1f}s/条  已用 {el/60:.1f}min", flush=True)

    print(f"\n[{_ts()}] 完成。写回成功 {written}，失败 {failed}。报告见 {REPORT_PATH}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="本次最多处理条数(0=全部)")
    p.add_argument("--dry-run", action="store_true", help="只统计不写回")
    p.add_argument("--concurrency", type=int, default=CONCURRENCY, help="并发度")
    args = p.parse_args()
    asyncio.run(main(args.limit, args.dry_run, args.concurrency))
