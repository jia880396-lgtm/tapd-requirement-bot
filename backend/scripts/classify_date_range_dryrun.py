"""只读探测：拉取 workspace 全部需求，按创建时间过滤 2026.7.1~2026.9.30，
核对 AI模块分类字段（custom_field_ai_module，默认 custom_field_32）的空值情况。
不写回 TAPD、不调用 LLM。"""
import asyncio
import sys
from datetime import datetime

from app.config import settings
from app.tapd_client import tapd_client


async def main():
    ws = settings.tapd_workspace_ids.split(",")[0].strip()
    field = settings.custom_field_ai_module
    print(f"workspace={ws}  AI模块分类字段={field}")

    lo = datetime(2026, 7, 1, 0, 0, 0)
    hi = datetime(2026, 9, 30, 23, 59, 59)

    print("正在拉取全部需求（分页）...")
    stories = await tapd_client.get_stories_all(workspace_id=ws, limit_per_page=200, max_pages=60)
    print(f"共拉取 {len(stories)} 条需求")

    total = len(stories)
    in_range = 0
    empty_field = 0
    nonempty_field = 0
    parse_fail = 0
    samples = []
    empty_samples = []

    for item in stories:
        s = item.get("Story", item) if isinstance(item, dict) else {}
        created_raw = s.get("created", "")
        story_id = s.get("id", "")
        title = s.get("name", "")
        val = s.get(field, "") or ""
        val = val.strip() if isinstance(val, str) else str(val).strip()

        # 解析创建时间
        created = None
        if created_raw:
            try:
                created = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S")
            except Exception:
                parse_fail += 1
        if created is None:
            continue
        if not (lo <= created <= hi):
            continue

        in_range += 1
        if not val:
            empty_field += 1
            if len(empty_samples) < 8:
                empty_samples.append((story_id, created_raw, title))
        else:
            nonempty_field += 1
            if len(samples) < 8:
                samples.append((story_id, created_raw, val, title))

    print("=" * 60)
    print(f"拉取总数            : {total}")
    print(f"创建时间在范围内    : {in_range}")
    print(f"  ├─ 字段为空(需分类): {empty_field}")
    print(f"  └─ 字段非空(跳过)  : {nonempty_field}")
    print(f"创建时间解析失败跳过: {parse_fail}")
    print("=" * 60)
    print(f"\n[样本] 字段已填的需求(前8条):")
    for sid, c, v, t in samples:
        print(f"  {c} | {v} | {t[:40]}")
    print(f"\n[样本] 字段为空的需求(前8条):")
    for sid, c, t in empty_samples:
        print(f"  {c} | {sid} | {t[:40]}")


if __name__ == "__main__":
    asyncio.run(main())
