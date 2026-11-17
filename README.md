# A 股免费行情数据源手册

> 不用注册、不用 Token、不用付费。全部是网页前端调用的公开 HTTP 端点。
>
> 每条结论都来自实测，环境：A 股，2026-11。这些不是官方 API，没有 SLA，
> 随时可能变——所以文末专门写了「怎么验证一个源还活着」。

## 为什么整理这份东西

搜"免费 A 股数据源"能搜到一堆库（AKShare、efinance、adata……），但它们
**基本都是同一批端点的封装**，主要就是东方财富。换库不解决上游挂掉的问题。

真正需要知道的是三件事：

1. 哪个端点负责什么（同一个域名下，不同参数的可用性可能完全不同）
2. 字段单位是什么（差 10000 倍不会报错，只会静默算错）
3. 挂了怎么判断（很多失败是 **HTTP 200 + 空内容**，不是 4xx）

这份手册就是这三件事的答案，附可直接运行的示例代码。

---

## 一、实测总表

| # | 用途 | 端点 | 状态 | 备注 |
|---|---|---|---|---|
| 1 | 全市场个股快照 | `push2.eastmoney.com/api/qt/clist/get` | ✅ 主源 | 5000+ 只，100 条/页 |
| 2 | 板块列表 | 同上，`fs=m:90+t:2`（行业）/ `t:3`（概念） | ⚠️ 会整段失效 | 见坑 3 |
| 3 | 板块成分股 | 同上，`fs=b:BK0448` | ✅ | 与 #2 参数不同 |
| 4 | ETF 行情 | 同上，`fs=b:MK0021` | ✅ | 含主力净流入 |
| 5 | 日线 OHLCV | `push2his.eastmoney.com/api/qt/stock/kline/get` | ✅ | 1300 根，含成交额 |
| 6 | 涨停/跌停家数 | `push2ex.eastmoney.com/getTopicZTPool` / `DTPool` | ✅ | 不同子域，独立限流 |
| 7 | 两融历史 | `datacenter-web.eastmoney.com/api/data/v1/get` | ✅ | 320 日 |
| 8 | ETF 季度份额 | `fundf10.eastmoney.com/FundArchivesDatas.aspx` | ✅ | 返回 JS 片段，非 JSON |
| 9 | 7×24 快讯 | `np-listapi.eastmoney.com/comm/web/getFastNewsList` | ✅ | 50 条标题 |
| 10 | 隔夜美股 | `push2.eastmoney.com/api/qt/ulist.np/get` | ✅ | `secids=105.NVDA` |
| 11 | 全市场快照（备用） | `vip.stock.finance.sina.com.cn/.../Market_Center.getHQNodeData` | ✅ | 5574 只 / 3.6s |
| 12 | 板块列表（备用） | `vip.stock.finance.sina.com.cn/q/view/newSinaHy.php` | ✅ 仅列表 | **无板块日线** |
| 13 | 日线（备用） | `web.ifzq.gtimg.cn/appstock/app/fqkline/get` | ✅ | **无成交额** |
| 14 | 网易日线 | `quotes.money.163.com/service/chddata.html` | ❌ 502 | 多次重试均失败 |
| 15 | 同花顺板块 | `q.10jqka.com.cn` / `d.10jqka.com.cn` | ⚠️ 需 cookie | `hexin-v` 由页面 JS 生成 |

```bash
# 一键体检：把上面所有源跑一遍，输出状态表
python examples/check.py
```

---

## 二、快速开始

三个最常用的调用，**注意 `end` 参数**：

```python
import requests

# 日线（上证指数，前复权，最近 3 根）
r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params={
    "secid": "1.000001", "klt": 101, "fqt": 1, "lmt": 3,
    "end": "20500101",                       # 必填！不带会返回 data: null
    "fields1": "f1,f2,f3,f4,f5,f6",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
}, timeout=20)
klines = r.json()["data"]["klines"]          # ["日期,开,收,高,低,量,额,振幅,涨跌幅,涨跌额,换手率", ...]
```

```python
# 全市场快照（第 1 页 100 只）
r = requests.get("https://push2.eastmoney.com/api/qt/clist/get", params={
    "pn": 1, "pz": 100, "po": 1, "np": 1,
    "fltt": 2, "invt": 2, "fid": "f3",
    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
    "fields": "f2,f3,f6,f8,f9,f10,f12,f14,f20,f21,f62,f100,f184",
}, timeout=20)
diff = r.json()["data"]["diff"]
```

```python
# 新浪全市场（备用源，注意 Referer 与万元单位）
r = requests.get(
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
    params={"page": 1, "num": 100, "sort": "symbol", "asc": 1, "node": "hs_a"},
    headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
    timeout=20,
)
rows = r.json()      # mktcap/nmc 单位是万元，要 ×10000
```

更多示例见 [`examples/`](examples/)。

---

## 三、逐源要点

完整字段表与参数见 [`examples/`](examples/) 里的注释。这里只列**容易踩的**。

### 东财 clist（全市场 / 板块 / ETF）

- `pz` 上限 **100**，5500 只要翻 56 页
- **`fltt=2` 不能省**，否则返回字符串型数值，后续计算全错
- 返回结构 `{"data":{"total":5574,"diff":[...]}}`

字段：

| 编号 | 含义 | 单位 |
|---|---|---|
| f2 / f3 | 现价 / 涨跌幅 | 元 / % |
| f5 / f6 | 成交量 / 成交额 | 手 / **元** |
| f8 | 换手率 | % |
| f9 / f10 | 市盈率 / 量比 | 倍 |
| f12 / f14 | 代码 / 名称 | — |
| f20 / f21 | 总市值 / 流通市值 | **元** |
| f26 | 上市日期 | `YYYYMMDD` |
| f62 / f184 | 主力净流入 / 净占比 | **元** / % |
| f100 | 所属行业 | — |

### 东财 kline（日线）

- `secid` 格式 `市场.代码`：`1` 沪市、`0` 深市、`90.BK0448` 板块、`105.NVDA` 美股
- `klt`：101 日 / 102 周 / 5 五分钟
- **`end` 必填**，填 `20500101` 表示"到最新"
- 五分钟线一次约 1500 根 ≈ 32 个交易日，**不支持翻页**

### 新浪（备用全市场）

- **必须带 `Referer: https://finance.sina.com.cn`**
- `num` 上限 **100**
- `mktcap` / `nmc` 单位是**万元**（东财是元）
- 没有量比、主力净流入、上市日期、行业

### 新浪（板块）

- 列表返回的是 JS 赋值语句 `var S_Finance_bankuai_sinaindustry = {...}`，要正则截取
- 板块代码 `new_xxx` 与东财 `BKxxxx` **是两套体系，不能混用**
- **板块日线拿不到**：`CN_MarketData.getKLineData` 对板块代码返回 `null`

### 腾讯（备用日线）

```
https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,1300,qfq
```

- `param` 格式：`代码,周期,起,止,数量,复权`
- 返回 `[日期, 开, 收, 高, 低, 成交量]`，**没有成交额**
- 注意区分：`qt.gtimg.cn` 是**实时**行情，历史 K 线在 `web.ifzq.gtimg.cn`

---

## 四、降级策略：按端点设计，不是按数据商

实测过一次：

> `push2.eastmoney.com/api/qt/clist/get` 的 `m:` 类查询整段返回空，
> 而同一时刻 `b:` 类（成分股、ETF）、`push2his`（日线）、
> `datacenter`（两融）、`push2ex`（涨停池）全部正常。

所以"东财挂了"这个判断太粗。真正需要备份的只有会一起挂的那几个端点：

| 能力 | 主源 | 备用 | 覆盖情况 |
|---|---|---|---|
| 全市场快照 | 东财 clist | 新浪 | 有，缺量比/主力净流入/行业 |
| 日线 | 东财 kline | 腾讯 | 有，缺成交额 |
| 板块列表 / 日线 | 东财 | **无** | 新浪无板块日线 |
| ETF | 东财 | **无** | 新浪无主力净流入，而排序依赖它 |
| 两融 / 涨停 / 新闻 / 外盘 | 各自子域 | 不需要 | 子域独立，通常不同时挂 |

**板块为什么不硬做备份**：拉成分股等权合成"板块日线"技术上可行，但那是另一条指数，
与官方板块指数口径不同，历史序列会断在切换那天。为了"今天能跑"污染历史，不划算。

---

## 五、坑清单

### 1. HTTP 200 + 空内容（最常见的伪成功）

东财被限流时不返回 4xx，而是 `{"data":null}`。同类还有：

- kline 少 `end` 参数 → `{"rc":102,"data":null}`
- 板块列表限流 → `diff` 是空数组
- 新浪翻页超出范围 → `[]`

**只检查状态码会把"没拿到"当成"今天没有数据"，两者含义相反。**

判据要用"应该非空"：全市场正常 5000+，拿到 0 或 100 就是失败。

### 2. 单位不一致

| 数据 | 东财 | 新浪 |
|---|---|---|
| 市值 | 元 | **万元** |
| 成交量 | 手 | **股** |
| 成交额 | 元 | 元 |

不换算不会报错，只会静默算错。标准化之后排序可能还对，但所有绝对数值全错。

### 3. `m:` 类与 `b:` 类可用性不同步

`m:0+t:6`（全市场）、`m:90+t:2`（板块）会一起失效，
而 `b:BKxxxx`（成分股）、`b:MK0021`（ETF）仍然正常。

### 4. NaN 混进 JSON

部分接口返回 `NaN`（非标准 JSON 字面量），浏览器 `JSON.parse` 直接抛
`Unexpected token 'N'`，整页数据作废。序列化前要把 NaN/Inf 转成 `null`。

### 5. 反复探测会加剧限流

连续请求十几次，可能从"部分可用"变成"整段不可用"。
验证时每次至少隔 2 秒。

### 6. 板块代码不通用

东财 `BK0448`、新浪 `new_blhy`、同花顺 `881101` 是三套独立编码，混用会静默返回空。

### 7. 成交量 ≠ 成交额

备用日线源只有成交量。用 `成交量 × 收盘价` 估成交额看着合理，但复权价与原价差得远，
估出来的量能因子会系统性偏移。**缺就说缺。**

---

## 六、怎么验证一个源还活着

不要相信文档，也不要相信"别人说能用"。

1. **打最小请求**：只取 3 条、只留必要字段
2. **看 body 不看状态码**：200 + `{"data":null}` 等于失败
3. **断言"应该非空"**：全市场 < 1000 只、板块 < 20 个，一律判失败
4. **核对单位**：拿一个已知市值的股票（比如工商银行 ≈ 2 万亿）验证量级，
   差 10000 倍就是万元/元的坑
5. **交叉验证**：同一天同一只股票的成交量，两个源差十倍，
   通常是复权口径不一致，不是源坏了
6. **控制节奏**：每次间隔 2 秒以上

`examples/check.py` 把 1–3 步做成了自动化，改完可以顺手跑一遍。

---

## 七、合规

- 这些是**网页前端调用的接口**，不是官方 API。没有 SLA，随时可能变。
- 个人研究、低频拉取通常没问题。**不要高频轮询、不要高并发**
  （参考量级：全市场快照并发 6 页，单次完整抓取约 70 个请求）。
- 不要用于商业分发或二次售卖数据。
- 数据仅供研究，不构成投资建议。

## License

MIT
