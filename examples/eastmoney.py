"""东方财富行情接口示例。

只依赖 requests，不引入 pandas —— 把"怎么调"和"怎么处理数据"分开，
你看完接口部分就能套到自己的技术栈里。

运行：python examples/eastmoney.py
"""
from __future__ import annotations

import requests

BASE = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
UA = {"User-Agent": "Mozilla/5.0"}


def _get(url: str, params: dict, timeout: int = 20) -> dict:
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# 日线
# ---------------------------------------------------------------------------
def kline(secid: str = "1.000001", limit: int = 3, klt: int = 101) -> list[list[str]]:
    """日线（前复权）。

    secid 格式是「市场.代码」：
        1.000001   上证指数（1 = 沪市）
        0.399001   深证成指（0 = 深市）
        90.BK0448  板块
        105.NVDA   美股

    klt：101 日线 / 102 周线 / 5 五分钟

    ⚠️ end 必填。不带会返回 {"rc":102,"data":null}——HTTP 200、结构正常、
       就是没有数据。这是最容易误判的一种失败。
    """
    j = _get(KLINE, {
        "secid": secid, "klt": klt, "fqt": 1, "lmt": limit,
        "end": "20500101",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    })
    data = j.get("data")
    if not data or not data.get("klines"):
        # 关键：不要只看 status_code。data 为 null 就是失败，
        # 不能当成"这只股票没有历史"。
        raise RuntimeError(f"日线为空：rc={j.get('rc')} secid={secid}")
    # 每行：日期,开,收,高,低,成交量(手),成交额(元),振幅,涨跌幅,涨跌额,换手率
    return [row.split(",") for row in data["klines"]]


# ---------------------------------------------------------------------------
# 全市场快照
# ---------------------------------------------------------------------------
SPOT_FIELDS = "f2,f3,f5,f6,f8,f9,f10,f12,f14,f20,f21,f26,f62,f100,f184"


def spot_page(page: int = 1, size: int = 100) -> tuple[int, list[dict]]:
    """全市场快照的一页，返回 (总数, 本页记录)。

    pz 上限是 100，5500 只要翻 56 页。

    字段（数字是东财内部编号）：
        f2  现价(元)      f3  涨跌幅(%)
        f5  成交量(手)    f6  成交额(元)
        f8  换手率(%)     f9  市盈率      f10 量比
        f12 代码          f14 名称
        f20 总市值(元)    f21 流通市值(元)
        f26 上市日期      f62 主力净流入(元)   f184 净占比(%)
        f100 所属行业
    """
    j = _get(BASE, {
        "pn": page, "pz": size, "po": 1, "np": 1,
        "fltt": 2,          # ⚠️ 不能省，否则数值是字符串
        "invt": 2, "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": SPOT_FIELDS,
    })
    data = j.get("data") or {}
    diff = data.get("diff") or []
    if page == 1 and not diff:
        # 第一页就空 = 被限流，不是"今天没有股票"
        raise RuntimeError("全市场快照为空，疑似限流")
    return int(data.get("total") or 0), diff


def spot_all(max_pages: int = 60) -> list[dict]:
    """全市场全部记录。正常 5000+ 只，少于 1000 视为失败。"""
    total, first = spot_page(1)
    rows = list(first)
    pages = min((total + 99) // 100, max_pages)
    for p in range(2, pages + 1):
        _, chunk = spot_page(p)
        rows.extend(chunk)
    if len(rows) < 1000:
        raise RuntimeError(f"全市场只拿到 {len(rows)} 只，判定失败")
    return rows


# ---------------------------------------------------------------------------
# 板块
# ---------------------------------------------------------------------------
def sector_list(kind: str = "industry") -> list[dict]:
    """板块列表。

    fs=m:90+t:2 行业 / m:90+t:3 概念

    ⚠️ 这一类的可用性与 b: 类不同步：实测中 m: 类整段返回空时，
       b:BKxxxx（板块成分）、b:MK0021（ETF）仍然正常。
       所以"东财挂了"这个判断要精确到 url + 参数，不能一刀切。
    """
    fs = "m:90+t:2" if kind == "industry" else "m:90+t:3"
    j = _get(BASE, {
        "pn": 1, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "fs": fs,
        "fields": "f2,f3,f6,f8,f12,f14,f20,f62,f104,f105,f128,f136,f140,f184",
    })
    diff = ((j.get("data") or {}).get("diff")) or []
    if not diff:
        raise RuntimeError(f"板块列表为空（{kind}），疑似限流")
    return diff


def sector_members(code: str = "BK0448", size: int = 100) -> list[dict]:
    """某个板块的成分股。code 形如 BK0448。"""
    j = _get(BASE, {
        "pn": 1, "pz": size, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "fs": f"b:{code}",
        "fields": "f2,f3,f6,f12,f14,f20,f21",
    })
    return ((j.get("data") or {}).get("diff")) or []


def etf_list(size: int = 100) -> list[dict]:
    """ETF 行情（含主力净流入）。fs=b:MK0021。"""
    j = _get(BASE, {
        "pn": 1, "pz": size, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "fs": "b:MK0021",
        "fields": "f2,f3,f6,f12,f14,f20,f21,f62,f184",
    })
    return ((j.get("data") or {}).get("diff")) or []


# ---------------------------------------------------------------------------
# 两融（不同子域，限流独立）
# ---------------------------------------------------------------------------
def margin(days: int = 5) -> list[dict]:
    """融资融券历史。

    走 datacenter-web 而不是 push2 —— 两者子域不同、限流各自独立，
    push2 被限时这里通常仍然可用。

    字段：RZYE 融资余额 / RZYEZB 占流通市值% / RZJME 净买入 / RQYE 融券余额
    """
    j = _get(DATACENTER, {
        "reportName": "RPTA_RZRQ_LSHJ", "columns": "ALL",
        "pageSize": days, "sortColumns": "DIM_DATE", "sortTypes": -1,
    })
    return ((j.get("result") or {}).get("data")) or []


if __name__ == "__main__":
    print("日线（上证指数最近 3 根）")
    for row in kline():
        print("  ", row[0], "收", row[2], "额", row[6])

    total, page = spot_page(1, 5)
    print(f"\n全市场：共 {total} 只，本页 {len(page)} 只")
    for x in page:
        print(f"   {x['f12']} {x['f14']:<8} 现价 {x['f2']}  市值 {x['f20']}")

    print(f"\n行业板块：{len(sector_list())} 个")
    print(f"板块 BK0448 成分股：{len(sector_members())} 只")
    print(f"ETF：{len(etf_list())} 只")
    print(f"两融最近记录：{len(margin())} 条")
