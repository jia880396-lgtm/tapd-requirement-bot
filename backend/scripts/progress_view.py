# -*- coding: utf-8 -*-
r"""
AI 模块分类写回任务 —— 进度查看器（只读，可反复执行）

用法（任选其一，在项目根目录 backend/ 下）：
  项目 venv:   .venv\Scripts\python.exe scripts\progress_view.py
  系统 python: python scripts\progress_view.py

说明：
  - 读取 scripts/classify_run_report.jsonl（全量任务实时追加的结果）
  - 按 story_id 去重统计，给出进度 / 成功 / 失败 / 跳过 / 速率 / 预计完成时间
"""
import json
import os
import datetime

REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classify_run_report.jsonl")
TOTAL_TARGET = 3207  # 时间范围内、字段为空的待分类需求总数（脚本启动时打印确认）


def parse_time(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def main():
    if not os.path.exists(REPORT):
        print("[进度] 报告文件尚未生成，任务可能刚启动或已结束。")
        return

    rows = [json.loads(l) for l in open(REPORT, encoding="utf-8") if l.strip()]

    # 按 story_id 去重（全量任务幂等续跑时，重复行以最后一条为准）
    seen = {}
    for r in rows:
        seen[r.get("story_id")] = r
    uniq = list(seen.values())

    written = sum(1 for r in uniq if r.get("status") == "written")
    errors = sum(1 for r in uniq if r.get("status") == "error")
    skipped = sum(1 for r in uniq if r.get("status") == "skip_existing")
    done = len(uniq)
    pct = done / TOTAL_TARGET * 100 if TOTAL_TARGET else 0

    print("=" * 46)
    print("   AI 模块分类写回 —— 执行进度")
    print("=" * 46)
    print(f"  目标待分类总数 : {TOTAL_TARGET}")
    print(f"  已处理(去重)   : {done}   ({pct:.1f}%)")
    print(f"    成功写回     : {written}")
    print(f"    失败         : {errors}")
    print(f"    已存在跳过   : {skipped}")

    times = [parse_time(r.get("time")) for r in uniq if parse_time(r.get("time"))]
    if len(times) >= 2:
        span = (max(times) - min(times)).total_seconds()
        if span > 0 and done > 1:
            per = span / done
            remain = (TOTAL_TARGET - done) * per
            eta = datetime.datetime.now() + datetime.timedelta(seconds=remain)
            print(f"  平均速率       : {per:.1f} 秒/条")
            print(f"  预计剩余       : {remain / 3600:.1f} 小时")
            print(f"  预计完成       : {eta.strftime('%Y-%m-%d %H:%M:%S')}")

    print("-" * 46)
    print("  最近 5 条:")
    for r in rows[-5:]:
        print(f"    {r.get('time','')}  {r.get('story_id')} -> {r.get('value')}  [{r.get('status')}]")

    if errors:
        print("-" * 46)
        print("  最近失败样例:")
        for r in [x for x in rows if x.get("status") == "error"][-3:]:
            print(f"    {r.get('story_id')}: {str(r.get('error'))[:150]}")
    print("=" * 46)


if __name__ == "__main__":
    main()
