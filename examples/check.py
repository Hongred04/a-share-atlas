"""一键体检：把手册里的数据源全部跑一遍，输出状态表。

只依赖 requests。

运行：python examples/check.py

为什么需要这个
    这些接口没有文档、没有 SLA，随时可能变。光看别人写的教程没用——
    半年后的教程可能已经全部失效。所以留一个能随时跑的体检脚本：
    改完代码、或者哪天上不去网，先跑这个确认是"源挂了"还是"自己写错了"。

判定原则
    不看 HTTP 状态码，看**内容是否达到应有的量级**。
    东财限流时返回的是 200 + {"data":null}，状态码完全正常。
    全市场正常 5000+ 只，拿到 0 就是失败，不是"今天股票少"。
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import eastmoney as em  # noqa: E402
import sina  # noqa: E402
import tencent as tx  # noqa: E402


def _em_kline():
    rows = em.kline(limit=3)
    if len(rows) < 3:
        raise RuntimeError(f"只有 {len(rows)} 根")
    return f"{len(rows)} 根 · 最新 {rows[-1][0]} 收 {rows[-1][2]}"


def _em_spot():
    total, page = em.spot_page(1, 100)
    if total < 3000 or len(page) < 50:
        raise RuntimeError(f"总数 {total} / 本页 {len(page)}，量级不对")
    return f"{total} 只 · 本页 {len(page)}"


def _em_sector():
    rows = em.sector_list("industry")
    if len(rows) < 20:
        raise RuntimeError(f"只有 {len(rows)} 个，正常约 60")
    return f"{len(rows)} 个行业板块"


def _em_margin():
    rows = em.margin(days=3)
    if not rows:
        raise RuntimeError("空返回")
    return f"{len(rows)} 条 · 最新 {str(rows[0].get('DIM_DATE'))[:10]}"


def _sina_spot():
    rows = sina.spot_page(1, 100)
    if len(rows) < 50:
        raise RuntimeError(f"只有 {len(rows)} 条")
    return f"本页 {len(rows)} 条 · 首条 {rows[0]['code']} {rows[0]['name']}"


def _sina_sector():
    rows = sina.sector_list("industry")
    if len(rows) < 10:
        raise RuntimeError(f"只有 {len(rows)} 个")
    return f"{len(rows)} 个行业板块"


def _tx_kline():
    rows = tx.kline(count=20)
    if len(rows) < 5:
        raise RuntimeError(f"只有 {len(rows)} 根")
    return f"{len(rows)} 根 · 最新 {rows[-1][0]} 收 {rows[-1][2]}"


CHECKS = [
    ("东财 · 日线", _em_kline),
    ("东财 · 全市场快照", _em_spot),
    ("东财 · 行业板块", _em_sector),
    ("东财 · 两融", _em_margin),
    ("新浪 · 全市场（备用）", _sina_spot),
    ("新浪 · 板块列表（备用）", _sina_sector),
    ("腾讯 · 日线（备用）", _tx_kline),
]

# 已知不可用 / 有条件可用，单独列出，不参与通过率
NOTES = [
    ("网易 · 日线", "实测持续 502，不可用"),
    ("同花顺 · 板块", "需要 hexin-v cookie，不适合自动降级"),
    ("新浪 · 板块日线", "接口存在但对板块代码返回 null，板块无历史可用"),
]


def main() -> int:
    print(f"{'数据源':<24} {'结果':<6} 详情")
    print("-" * 78)
    passed = 0
    for name, fn in CHECKS:
        t0 = time.time()
        try:
            detail = fn()
            ms = int((time.time() - t0) * 1000)
            print(f"{name:<24} {'✓':<6} {detail}  ({ms}ms)")
            passed += 1
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - t0) * 1000)
            print(f"{name:<24} {'✗':<6} {type(e).__name__}: {str(e)[:44]}  ({ms}ms)")
        # 控制节奏：连续快打容易被限流，反而测出假故障
        time.sleep(2)

    print("-" * 78)
    print(f"通过 {passed}/{len(CHECKS)}")
    print()
    print("已知情况（不参与统计）：")
    for name, note in NOTES:
        print(f"  · {name}：{note}")
    if passed < len(CHECKS):
        print()
        print("有源失败。先确认是限流还是真的改版：等几分钟再跑一次，")
        print("仍然失败再看返回内容——是 data 为 null（限流/参数错）还是 404（改版）。")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
