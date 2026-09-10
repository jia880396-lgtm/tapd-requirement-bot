# -*- coding: utf-8 -*-
r"""
AI 模块分类写回任务 —— 动态进度条（实时刷新，可 Ctrl+C 退出）

用法（在项目根目录 backend/ 下）：
  动态刷新（持续运行，Ctrl+C 退出）:
      .venv\Scripts\python.exe scripts\progress_bar.py
  只看一眼当前快照（打印一次即退出）:
      .venv\Scripts\python.exe scripts\progress_bar.py --once
  指定其它报告文件与总数（用于重分类等子任务）:
      .venv\Scripts\python.exe scripts\progress_bar.py --once ^
          --report scripts/reclassify_report.jsonl --total 62
      # 动态模式同理，去掉 --once 即可

说明：脚本默认只读 classify_run_report.jsonl，每 2 秒重绘进度条；
      Ctrl+C 仅停止显示，后台分类任务不受影响。
"""
import json
import os
import sys
import time
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "classify_run_report.jsonl")
TOTAL_TARGET = 3207      # 时间范围内、字段为空的待分类需求总数
REFRESH = 2              # 刷新间隔（秒）

# 支持通过命令行指定不同的报告文件与总数（用于重分类等子任务）
# 例: python progress_bar.py --report scripts/reclassify_report.jsonl --total 62
import argparse as _argparse
_a = _argparse.ArgumentParser(add_help=False)
_a.add_argument("--report", default=REPORT)
_a.add_argument("--total", type=int, default=TOTAL_TARGET)
_a.add_argument("--once", action="store_true")
_a.add_argument("--refresh", type=int, default=REFRESH)
_ns, _ = _a.parse_known_args()
REPORT = _ns.report
TOTAL_TARGET = _ns.total
REFRESH = _ns.refresh
ONCE = _ns.once


def parse_time(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def read_stats():
    if not os.path.exists(REPORT):
        return None
    rows = [json.loads(l) for l in open(REPORT, encoding="utf-8") if l.strip()]
    seen = {}
    for r in rows:
        seen[r.get("story_id")] = r
    uniq = list(seen.values())
    written = sum(1 for r in uniq if r.get("status") == "written")
    errors = sum(1 for r in uniq if r.get("status", "").endswith("_error") or r.get("status") == "error")
    skipped = sum(1 for r in uniq if r.get("status") in ("skip_existing", "skip_valid"))
    done = len(uniq)
    times = [parse_time(r.get("time")) for r in uniq if parse_time(r.get("time"))]
    per = None
    eta = None
    if len(times) >= 2 and done > 1:
        span = (max(times) - min(times)).total_seconds()
        if span > 0:
            per = span / done
            remain = (TOTAL_TARGET - done) * per
            eta = datetime.datetime.now() + datetime.timedelta(seconds=remain)
    return done, written, errors, skipped, per, eta


def bar(pct, width=30):
    filled = int(round(pct * width / 100))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def render(done, written, errors, skipped, per, eta):
    pct = done / TOTAL_TARGET * 100 if TOTAL_TARGET else 0
    per_s = f"{per:.1f}s/条" if per else "  --  "
    eta_s = eta.strftime("%m-%d %H:%M") if eta else "  --  "
    return (f"{bar(pct)} {pct:5.1f}%  {done}/{TOTAL_TARGET}  "
            f"ok={written} fail={errors} skip={skipped}  {per_s}  ETA {eta_s}")


def main():
    if ONCE:
        st = read_stats()
        if not st:
            print("[进度] 报告文件尚未生成，任务可能刚启动或已结束。")
            return
        done, w, e, s, per, eta = st
        print(render(done, w, e, s, per, eta))
        return

    print("实时进度条（Ctrl+C 退出显示，后台任务继续）...")
    try:
        while True:
            st = read_stats()
            if st:
                done, w, e, s, per, eta = st
                print("\r" + render(done, w, e, s, per, eta) + "   ", end="", flush=True)
                if done >= TOTAL_TARGET:
                    print()
                    print("✅ 全部完成！")
                    break
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        print("\n已停止进度显示（后台分类任务仍在继续）。")


if __name__ == "__main__":
    main()
