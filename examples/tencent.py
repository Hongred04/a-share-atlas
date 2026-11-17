"""腾讯行情接口示例（东方财富日线的备用源）。

只依赖 requests。

运行：python examples/tencent.py

一个常见混淆：腾讯有两个域名，作用完全不同——

    qt.gtimg.cn            实时行情（现价、五档盘口）
    web.ifzq.gtimg.cn     历史 K 线（本文件用的这个）

搜到的很多代码写的是前者，拿不到历史数据不是接口挂了，是用错了域名。
"""
from __future__ import annotations

import requests

KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def kline(symbol: str = "sh000001", count: int = 10, period: str = "day") -> list[list[str]]:
    """日线。

    param 的格式是「代码,周期,起,止,数量,复权」：
        sh000001,day,,,1300,qfq
        ├ 代码   ├ 周期  ││  ├ 数量  └ 复权（qfq 前复权 / hfq 后复权 / 空 不复权）
        │        │      └┴ 起止留空表示"到最新"
        │        └ day / week / month
        └ 前缀 sh 沪市、sz 深市

    返回每行：[日期, 开, 收, 高, 低, 成交量]

    ⚠️ **没有成交额**。只有成交量（单位：手）。
       想用「成交量 × 收盘价」估成交额的话要注意：复权价与原价差得远，
       估出来的量能因子会系统性偏移。宁可少一个因子，也别编一个数字。

    ⚠️ 只支持 A 股与指数。板块（90.BKxxxx）和美股（105.xxx）没有对应代码。
    """
    r = requests.get(KLINE, params={
        # count 就是你要的根数，不要在这里偷偷加下限——
        # 调用方传 1 就该得到 1 条，否则调试时会被"为什么多出 19 条"困住
        "param": f"{symbol},{period},,,{max(int(count), 1)},qfq",
    }, headers=HEADERS, timeout=20)
    r.raise_for_status()
    j = r.json()
    arr = (((j.get("data") or {}).get(symbol)) or {}).get(period) or []
    return [row for row in arr if len(row) >= 6]


def to_eastmoney_format(symbol: str = "sh000001", count: int = 10) -> list[dict]:
    """转成与东财日线一致的字典格式，方便两个源互换。

    secid 与 symbol 的对应关系：
        1.000001  ←→  sh000001
        0.399001  ←→  sz399001
    """
    rows = kline(symbol, count)
    out = []
    for d, o, c, h, low, v in (r[:6] for r in rows):
        out.append({
            "date": d,
            "open": float(o),
            "close": float(c),
            "high": float(h),
            "low": float(low),
            "volume": float(v),
            "amount": None,      # 这个源不提供，保持 None 而不是编造
        })
    return out


if __name__ == "__main__":
    rows = kline(count=5)
    print(f"上证指数最近 {len(rows)} 根（腾讯备用源）：")
    for d, o, c, h, low, v in (r[:6] for r in rows):
        print(f"   {d}  开 {o}  收 {c}  高 {h}  低 {low}  量 {v}")

    print("\n注意：没有成交额字段。下面的 amount 是 None，不是 0：")
    print("  ", to_eastmoney_format(count=1))
