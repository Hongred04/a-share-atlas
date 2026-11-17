"""新浪财经接口示例（东方财富的备用源）。

只依赖 requests。

运行：python examples/sina.py

新浪是东财挂了之后真正的"另一条腿"——它走的是完全不同的后端。
但用它之前必须知道三件事：要 Referer、每页上限 100、市值单位是万元。
"""
from __future__ import annotations

import json
import re

import requests

QUOTE = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
         "Market_Center.getHQNodeData")
KLINES = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
          "CN_MarketData.getKLineData")
SECTOR_HY = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
SECTOR_GN = "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class"

# ⚠️ 不带 Referer 大概率被拒（403 或空 body）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}


# ---------------------------------------------------------------------------
# 全市场快照
# ---------------------------------------------------------------------------
def spot_page(page: int = 1, size: int = 100) -> list[dict]:
    """全市场快照的一页。

    ⚠️ num 上限就是 100，传 500 也只会给你 100 条。5500 只要翻约 56 页。

    字段单位（这是最容易出错的地方）：
        trade          现价(元)
        changepercent  涨跌幅(%)
        volume         成交量(股)      ← 东财是「手」，这里差 100 倍
        amount         成交额(元)
        mktcap         总市值(**万元**)  ← 东财是「元」，这里差 10000 倍
        nmc            流通市值(**万元**)
        turnoverratio  换手率(%)
        per / pb       市盈率 / 市净率

    不换算不会报错，只会静默算错。做市值分位、行业市值这类绝对数值时，
    差了四个数量级的结果看起来仍然"像个数字"，极难发现。
    """
    r = requests.get(QUOTE, params={
        "page": page, "num": min(size, 100), "sort": "symbol", "asc": 1, "node": "hs_a",
    }, headers=HEADERS, timeout=20)
    r.raise_for_status()
    text = r.text.strip()
    if not text:
        return []
    rows = r.json()
    return rows if isinstance(rows, list) else []


def spot_all(max_pages: int = 60) -> list[dict]:
    """全市场全部记录，并把市值换算成元。"""
    first = spot_page(1)
    if not first:
        raise RuntimeError("新浪全市场第 1 页为空")
    rows = list(first)
    for p in range(2, max_pages + 1):
        chunk = spot_page(p)
        if not chunk:
            break
        rows.extend(chunk)
    if len(rows) < 1000:
        raise RuntimeError(f"只拿到 {len(rows)} 只，判定失败")
    for x in rows:
        # 万元 → 元
        x["mktcap_yuan"] = float(x["mktcap"]) * 10000 if x.get("mktcap") else None
        x["nmc_yuan"] = float(x["nmc"]) * 10000 if x.get("nmc") else None
    return rows


# ---------------------------------------------------------------------------
# 板块
# ---------------------------------------------------------------------------
def _parse_sector_js(text: str) -> list[dict]:
    """新浪板块接口返回的是 JS 赋值语句，不是 JSON。

    var S_Finance_bankuai_sinaindustry = {"new_blhy":"new_blhy,玻璃行业,19,13.83,..."}

    所以不能直接 json.loads，要先截出 {...} 那段。

    每条的字段顺序：代码,名称,家数,均价,涨跌,涨跌幅,成交量,成交额,领涨股代码,...
    """
    m = re.search(r"=\s*(\{.*\})", text, re.S)
    if not m:
        return []
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    out = []
    for code, line in raw.items():
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        out.append({
            "code": parts[0], "name": parts[1],
            "count": parts[2],          # 成分股家数
            "avg_price": parts[3],
            "pct": parts[5],            # 涨跌幅 %
            "amount": parts[7] if len(parts) > 7 else None,
            "leader": parts[12] if len(parts) > 12 else None,
        })
    return out


def sector_list(kind: str = "industry") -> list[dict]:
    """行业 / 概念板块列表。

    ⚠️ 这里的代码是 new_xxx，与东财的 BKxxxx 是两套体系，不能混用。
       想用新浪板块驱动东财的成分股查询是行不通的。
    """
    url = SECTOR_HY if kind == "industry" else SECTOR_GN
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return _parse_sector_js(r.text)


def sector_members(code: str = "new_jrhy", size: int = 100) -> list[dict]:
    """某个新浪板块的成分股。code 形如 new_jrhy。"""
    r = requests.get(QUOTE, params={
        "page": 1, "num": min(size, 100), "sort": "symbol", "asc": 1, "node": code,
    }, headers=HEADERS, timeout=20)
    text = r.text.strip()
    if not text:
        return []
    rows = r.json()
    return rows if isinstance(rows, list) else []


# ---------------------------------------------------------------------------
# K 线
# ---------------------------------------------------------------------------
def kline(symbol: str = "sh000001", datalen: int = 10, scale: int = 240) -> list[dict]:
    """日线。scale=240 是日线，5/15/30/60 是分钟线。

    symbol 支持：
        sh000001 / sz399001   指数
        sh600000 / sz000001   个股

    ⚠️ **不支持板块代码**：new_blhy / gn_hwqc / bk_881101 一律返回 null。
       这一条直接决定了"板块数据没有备用源"——拿不到板块历史，
       就算不出 5 日 / 20 日动量。
    """
    r = requests.get(KLINES, params={
        "symbol": symbol, "scale": scale, "ma": "no", "datalen": datalen,
    }, headers=HEADERS, timeout=20)
    r.raise_for_status()
    text = r.text.strip()
    if text in ("null", "", "[]"):
        return []
    data = r.json()
    return data if isinstance(data, list) else []


if __name__ == "__main__":
    rows = spot_page(1, 3)
    print(f"全市场第 1 页：{len(rows)} 条")
    for x in rows:
        wan = float(x["mktcap"]) if x.get("mktcap") else 0
        print(f"   {x['code']} {x['name']:<8} 现价 {x['trade']}  "
              f"市值 {wan:.0f} 万元 = {wan/10000:.1f} 亿元")

    print(f"\n行业板块：{len(sector_list('industry'))} 个")
    print(f"概念板块：{len(sector_list('concept'))} 个")

    k = kline(datalen=3)
    print(f"\n上证指数最近 {len(k)} 根：")
    for row in k:
        print("  ", row["day"], "收", row["close"])

    print(f"\n板块日线（应当为空）：{len(kline('new_blhy'))} 根")
