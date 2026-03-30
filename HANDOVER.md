# Arbitrage Dashboard 交接文档（稳定版）

> 最后更新：2026-03-16
> 作者：Claude (AI 开发助手)

---

## 一、项目概述

加密货币套利仪表盘，监控 Binance / OKX / Bybit 三大交易所的资费率、基差、价差等数据，提供套利机会发现和预警功能。

**技术栈：**
- 后端：Python 3.9 + FastAPI + SQLAlchemy 2.0 (async) + APScheduler
- 前端：React 19 + TypeScript + Ant Design 6 + Vite 7 + Zustand
- 数据库：MySQL (阿里云 RDS)，共享库 `dfs_network`，所有表名加 `arb_` 前缀
- 实时通信：WebSocket

**项目路径：** `arbitrage-dashboard`

---

## 二、环境与配置

### 2.1 后端环境

```bash
cd arbitrage-dashboard/backend
pip3 install -r requirements.txt
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2.2 前端环境

```bash
cd arbitrage-dashboard/frontend
npm install
npx vite --host 0.0.0.0   # 端口 5173
```

### 2.3 环境变量 (backend/.env)

```env
DATABASE_URL=mysql+aiomysql://<user>:<password>@<rds-host>:3306/dfs_network?charset=utf8mb4
JWT_SECRET=<your-jwt-secret>
JWT_ALGORITHM=HS256
JWT_EXPIRE_DAYS=7
ARBITRAGE_API_URL=http://<your-arbitrage-api-host>:9000
```

### 2.4 代理配置（重要）

本地环境变量设有 `http_proxy=http://127.0.0.1:10080`，影响所有 HTTP 请求。

| 目标 | 是否需要代理 | 处理方式 |
|------|------------|---------|
| 套利 API (<your-arbitrage-api-host>:9000) | **不需要** | `data_fetcher` 设 `trust_env=False`，`funding_break` 复用缓存 |
| Binance API (fapi.binance.com) | **需要** | `BinanceClient` 通过 `get_proxy()` 获取代理 |
| OKX / Bybit API | **需要** | 各自 client 通过 `get_proxy()` 获取代理 |
| curl 本地接口 | **不需要** | 命令行加 `--noproxy '*'` |

### 2.5 外部服务

| 服务 | 地址 | 用途 |
|------|------|------|
| MySQL RDS | `<your-rds-host>:3306` | 数据库 |
| 套利 API | `http://<your-arbitrage-api-host>:9000` | 实时套利数据（基差、开差、资费等） |
| 代理 | `http://127.0.0.1:10080` | 访问 Binance/OKX/Bybit |

---

## 三、核心架构

### 3.1 数据流总览

```
套利 API (<your-arbitrage-api-host>:9000)
   ↓ 每3秒，6个交易所对，分2批×3并发
data_fetcher._last_data（内存缓存，trust_env=False）
   ↓ 过滤只保留 LPerp_SPerp（永续对永续）
realtime_scheduler.refresh()（timeout=90s）
   ├── basis_monitor.process()     → 基差预警列表
   ├── unhedged_service.process()  → 非对冲机会列表
   ├── WebSocket broadcast         → 前端实时更新
   ├── alert_engine.process()      → 用户通知（WebSocket + 飞书）
   └── post_investment check       → 投后监控检查

funding_break_scheduler（每5秒）
   └── 复用 data_fetcher.get_cached_data()（不再独立请求API）
```

### 3.2 关键设计决策

1. **套利 API 数据过滤**：`data_fetcher.fetch_arbitrage_data()` 过滤 `chanceType == "LPerp_SPerp"`，只保留永续对永续数据，去掉现货对（减少 60%+ 数据量，避免读取超时）

2. **data_fetcher 不走代理**：`aiohttp.ClientSession(trust_env=False)` 禁止自动读取环境变量代理，因为套利 API 是直连地址

3. **funding_break 复用缓存**：`_fetch_self_api_data()` 不再自己请求套利 API，改为读取 `data_fetcher.get_cached_data()`，避免重复请求和超时

4. **1d 涨幅用 Binance ticker API**：`refresh_price_changes()` 通过 `GET /fapi/v1/ticker/24hr`（不传 symbol）一次获取所有币种 24h 涨跌幅，无需依赖 DB 中的 5m K线数据

5. **3d 涨幅用 DB 1d K线**：从 `arb_price_klines` 表查 1d 周期数据（保留 180 天），±1天窗口匹配 72h 前价格

6. **启动时数据密度检查**：`check_data_integrity()` 不只检查"有没有旧数据"，而是检查数据**密度**（实际 candle 数 >= 期望数的 70%），发现稀疏数据后加入 backfill 队列

7. **温和 backfill**：每 60 秒处理 2 个任务，顺序执行，1 秒间隔，遇到 418 (rate limit) 自动暂停

---

## 四、定时任务配置

| Scheduler | 间隔 | 首次延迟 | 核心逻辑 |
|-----------|------|---------|----------|
| **realtime** | 3s | 立即 | 拉取套利API → 基差/非对冲 → WebSocket → 预警 |
| **funding_break** | 数据5s / caps 1h | 立即 | 复用 data_fetcher 缓存 + 检测资费突破 |
| **funding_rank** | 1h | — | 从三所拉取资费历史 → 写入 DB → 计算排行 |
| **kline backfill** | 60s | 60s | 补全稀疏 K线数据（2个/次） |
| **kline refresh** | 5min | 5min | 增量拉取最新 K线（所有周期，limit=2） |
| **price_changes** | 5min | 10s | 1d 从 ticker API，3d 从 DB |
| **funding_cumulative** | 5min | 8s | DB 查询累计资费 |
| **price_trend** | 10min | — | 计算 MA20/60/120 多头排列 |
| **new_listing** | 30min | — | 从三所拉取新上线币种 |
| **oi_snapshot** | 5min | — | 按用户投后监控配置拉取 OI |
| **cleanup** | 24h | — | 清理过期数据 |

---

## 五、超时配置汇总

| 组件 | 设置 | 值 | 说明 |
|------|------|---|------|
| data_fetcher session | total | 120s | 套利 API 响应大（~630KB/对） |
| data_fetcher session | sock_read | 60s | 单次读取超时 |
| data_fetcher session | trust_env | False | 不走系统代理 |
| realtime_scheduler | tick timeout | 90s | 首次 6 对请求可能耗时 60-90s |
| BinanceClient | 默认 timeout | 15s | K线等小数据请求 |
| backfill | per-request timeout | 20s | 单个 K线补全请求 |
| funding_break self API | — | 不请求 | 复用 data_fetcher 缓存 |

---

## 六、已知问题与注意事项

### 6.1 启动后 1-2 分钟无实时数据

首次启动需要等 realtime_scheduler 完成第一次 6 对请求（~60-90 秒），期间基差/开差为空。这是正常行为。

### 6.2 K线数据可能稀疏

`kline_scheduler.refresh()` 每 5 分钟拉 545 币 × 5 周期 = 2725 请求（并发 3），5 分钟跑不完。因此 DB 中 5m/1h K线数据可能不连续。1d 涨幅已改用 Binance ticker API 解决，不受此影响。

### 6.3 Binance 418 封禁

大量并发请求会触发 Binance 418 "I'm a teapot" 限流。backfill 检测到 418 会自动暂停。如被封需要切换 IP。

### 6.4 代理切换后需重启

切换 IP/代理后需要重启后端，因为 aiohttp session 会复用旧连接。

### 6.5 Python 3.9 兼容性

不支持 `str | None` 语法，必须用 `Optional[str]`。
Python 3.9 的 aiohttp 对 TLS-in-TLS（HTTPS 代理请求 HTTPS）支持有限，会有 warning 但不影响功能。

### 6.6 套利 API 偶尔 502

`data_fetcher` 失败时保留上次缓存数据不清空（优雅降级）。

---

## 七、前端页面更新时间

所有 7 个数据页面右上角都显示"更新时间"：

| 页面 | 更新时间触发 |
|------|------------|
| 资费排行 (FundingRank) | 查询排行数据时 |
| 新上线 (NewListing) | 每 5 分钟轮询时 |
| 资费突破 (FundingBreak) | API/WebSocket 数据到达时 |
| 价格趋势 (PriceTrend) | API/WebSocket 数据到达时 |
| 基差监控 (BasisMonitor) | API/WebSocket 数据到达时 |
| 非对冲 (Unhedged) | API/WebSocket 数据到达时 |
| 预警配置 (AlertConfig) | 需登录 |

---

## 八、快速启动指南

```bash
# 终端 1：后端
cd arbitrage-dashboard/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：前端
cd arbitrage-dashboard/frontend
npx vite --host 0.0.0.0

# 访问 http://localhost:5173
# 注意：启动后等 1-2 分钟实时数据才会出来
```

### 验证数据

```bash
# 健康检查
curl -s --noproxy '*' http://127.0.0.1:8000/api/health

# 实时数据（等 60-90 秒后）
curl -s --noproxy '*' http://127.0.0.1:8000/api/funding-rank/realtime | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']))"

# 涨跌幅
curl -s --noproxy '*' http://127.0.0.1:8000/api/funding-rank/price-changes | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'1d:{sum(1 for v in d.values() if \"change_1d\" in v)}, 3d:{sum(1 for v in d.values() if \"change_3d\" in v)}')"

# 资费突破
curl -s --noproxy '*' http://127.0.0.1:8000/api/funding-break | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']))"
```

---

## 九、文件修改索引

| 要改的功能 | 后端文件 | 前端文件 |
|-----------|---------|---------|
| 套利API数据获取 | `services/data_fetcher.py` | — |
| 实时轮询逻辑 | `schedulers/realtime_scheduler.py` | — |
| K线拉取/补全 | `schedulers/kline_scheduler.py` | — |
| 涨跌幅计算 | `schedulers/kline_scheduler.py` (refresh_price_changes) | `pages/FundingRank/index.tsx` |
| 资费突破检测 | `services/funding_break.py` | `pages/FundingBreak/index.tsx` |
| 基差监控 | `services/basis_monitor.py` | `pages/BasisMonitor/index.tsx` |
| 非对冲检测 | `services/unhedged.py` | `pages/Unhedged/index.tsx` |
| 预警通知 | `services/alert_engine.py` + `lark_notifier.py` | `hooks/useWebSocket.ts` |
| 代理配置 | `config.py` (get_proxy) | — |
| 数据库表结构 | `models/*.py` | — |
