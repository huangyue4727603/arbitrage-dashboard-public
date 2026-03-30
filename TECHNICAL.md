# Arbitrage Dashboard 技术开发文档

## 1. 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | React 18 + TypeScript | SPA 单页应用 |
| UI 框架 | Ant Design | 表格、弹窗、表单等组件 |
| 状态管理 | Zustand | 轻量状态管理 |
| 后端 | Python 3.11 + FastAPI | 异步高性能框架 |
| 实时通信 | WebSocket (FastAPI built-in) | 后端推送实时数据 |
| 数据库 | MySQL 8.0 | 用户数据、预警配置、预警记录 |
| ORM | SQLAlchemy + Alembic | 数据库模型与迁移 |
| 任务调度 | APScheduler | 定时任务（数据采集、计算） |
| HTTP 客户端 | aiohttp | 异步请求交易所 API 和自有 API |
| 认证 | JWT (PyJWT) | 7天免登录 Token |

---

## 2. 项目结构

```
arbitrage-dashboard/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI 入口
│   │   ├── config.py                # 配置（数据库、API地址等）
│   │   ├── database.py              # 数据库连接
│   │   │
│   │   ├── models/                  # SQLAlchemy 数据模型
│   │   │   ├── user.py              # 用户表
│   │   │   ├── lark_bot.py          # Lark 机器人配置
│   │   │   ├── alert_config.py      # 预警配置（投后监测、基差预警、非对冲）
│   │   │   ├── alert_history.py     # 预警历史记录
│   │   │   └── basis_monitor.py     # 基差监控预警数据库（定时清零）
│   │   │
│   │   ├── routers/                 # API 路由
│   │   │   ├── auth.py              # 注册/登录/退出
│   │   │   ├── funding_rank.py      # 资金费率排行榜 + 资费统计器
│   │   │   ├── new_listing.py       # 新上线币种
│   │   │   ├── funding_break.py     # 资费即将突破结算周期
│   │   │   ├── price_trend.py       # 价格趋势
│   │   │   ├── basis_monitor.py     # 基差监控
│   │   │   ├── unhedged.py          # 非对冲机会
│   │   │   ├── alert.py             # 预警配置管理
│   │   │   └── settings.py          # 用户设置（主题）
│   │   │
│   │   ├── services/                # 业务逻辑层
│   │   │   ├── data_fetcher.py      # 统一数据获取（自有API + 交易所API）
│   │   │   ├── exchange/
│   │   │   │   ├── binance.py       # 币安 API 封装
│   │   │   │   ├── okx.py           # OKX API 封装
│   │   │   │   └── bybit.py         # Bybit API 封装
│   │   │   ├── funding_rank.py      # 资费排行计算
│   │   │   ├── new_listing.py       # 新上线检测
│   │   │   ├── funding_break.py     # 资费突破检测
│   │   │   ├── price_trend.py       # 均线计算
│   │   │   ├── basis_monitor.py     # 基差监控逻辑
│   │   │   ├── unhedged.py          # 非对冲机会逻辑
│   │   │   ├── alert_engine.py      # 预警引擎（统一处理通知）
│   │   │   └── lark_notifier.py     # Lark 机器人推送
│   │   │
│   │   ├── schedulers/              # 定时任务
│   │   │   ├── realtime_3s.py       # 3秒任务：基差监控、非对冲机会、投后监测
│   │   │   ├── realtime_5s.py       # 5秒任务：资费突破结算周期
│   │   │   ├── interval_1m.py       # 1分钟任务：开差刷新
│   │   │   ├── interval_5m.py       # 5分钟任务：新上线币种
│   │   │   ├── interval_10m.py      # 10分钟任务：价格趋势均线计算
│   │   │   └── interval_1h.py       # 1小时任务：资费数据刷新
│   │   │
│   │   ├── websocket/               # WebSocket 管理
│   │   │   ├── manager.py           # 连接管理器
│   │   │   └── handlers.py          # 消息处理
│   │   │
│   │   └── utils/
│   │       ├── auth.py              # JWT 工具
│   │       └── funding.py           # 资费正负处理等通用计算
│   │
│   ├── alembic/                     # 数据库迁移
│   ├── alembic.ini
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   │
│   │   ├── api/                     # API 请求封装
│   │   │   ├── auth.ts
│   │   │   ├── funding.ts
│   │   │   └── alert.ts
│   │   │
│   │   ├── components/              # 通用组件
│   │   │   ├── Layout.tsx           # 页面布局（Tab 切换）
│   │   │   ├── LoginModal.tsx       # 登录弹窗
│   │   │   ├── RegisterModal.tsx    # 注册弹窗
│   │   │   └── ThemeSwitch.tsx      # 主题切换
│   │   │
│   │   ├── pages/                   # Tab 页面
│   │   │   ├── FundingRank/         # 资金费率排行榜
│   │   │   │   ├── index.tsx
│   │   │   │   ├── RankTable.tsx    # 排行表格
│   │   │   │   ├── DetailModal.tsx  # 资费差额明细弹窗
│   │   │   │   └── Calculator.tsx   # 资费统计器弹窗
│   │   │   ├── NewListing/          # 新上线币种
│   │   │   ├── FundingBreak/        # 资费即将突破
│   │   │   ├── PriceTrend/          # 价格趋势
│   │   │   ├── BasisMonitor/        # 基差监控
│   │   │   ├── Unhedged/            # 非对冲机会
│   │   │   └── AlertConfig/         # 预警配置
│   │   │       ├── index.tsx
│   │   │       ├── LarkBotManager.tsx
│   │   │       ├── PostInvestment.tsx  # 投后监测
│   │   │       ├── BasisAlert.tsx      # 基差预警
│   │   │       └── UnhedgedAlert.tsx   # 非对冲预警
│   │   │
│   │   ├── stores/                  # Zustand 状态
│   │   │   ├── authStore.ts
│   │   │   ├── themeStore.ts
│   │   │   └── wsStore.ts           # WebSocket 数据状态
│   │   │
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts      # WebSocket 连接 Hook
│   │   │   └── useAuth.ts           # 认证 Hook
│   │   │
│   │   └── utils/
│   │       └── format.ts            # 格式化工具（百分比、小数等）
│   │
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── README.md                        # 产品需求文档
├── TECHNICAL.md                     # 技术开发文档（本文件）
└── docker-compose.yml               # 本地开发环境（MySQL）
```

---

## 3. 数据库设计

### 3.1 users（用户表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| username | VARCHAR(50) UNIQUE | 用户名 |
| password_hash | VARCHAR(255) | 密码哈希 |
| theme | ENUM('light','dark') | 主题偏好，默认 light |
| sound_enabled | TINYINT(1) | 声音提醒全局开关，默认 1 |
| popup_enabled | TINYINT(1) | 弹窗提醒全局开关，默认 1 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.2 lark_bots（Lark 机器人配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| user_id | INT | 外键 → users.id |
| name | VARCHAR(100) | 机器人名称 |
| webhook_url | VARCHAR(500) | Webhook 链接 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.3 post_investment_monitors（投后监测配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| user_id | INT | 外键 → users.id |
| coin_name | VARCHAR(20) | 币种名称 |
| long_exchange | VARCHAR(20) | 做多交易所 |
| short_exchange | VARCHAR(20) | 做空交易所 |
| spread_threshold | DECIMAL(10,4) | 开差阈值（选填，如 -0.005 表示 -0.5%） |
| price_threshold | DECIMAL(20,8) | 价格阈值（最低价） |
| oi_drop_1h_threshold | DECIMAL(10,4) | 1小时持仓跌幅阈值（如 -0.20） |
| oi_drop_4h_threshold | DECIMAL(10,4) | 4小时持仓跌幅阈值 |
| sound_enabled | TINYINT(1) | 声音开关 |
| popup_enabled | TINYINT(1) | 弹窗开关 |
| lark_bot_id | INT | 外键 → lark_bots.id（可空） |
| is_active | TINYINT(1) | 监测开关，默认 1 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.4 basis_alert_configs（基差预警个性化配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| user_id | INT UNIQUE | 外键 → users.id，一对一 |
| basis_threshold | DECIMAL(10,4) | 新机会基差阈值，默认 -1 |
| expand_multiplier | DECIMAL(10,4) | 基差扩大倍数，默认 1.1 |
| clear_interval_hours | INT | 清除预警周期（小时），默认 4，最小 1 |
| blocked_coins | TEXT | 不看的币种，逗号分隔 |
| sound_enabled | TINYINT(1) | 声音开关 |
| popup_enabled | TINYINT(1) | 弹窗开关 |
| lark_bot_id | INT | 外键 → lark_bots.id（可空） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 3.5 basis_alert_records（基差预警数据库记录 — 定时清零）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| user_id | INT | 外键 → users.id |
| coin_name | VARCHAR(20) | 币种名称 |
| last_basis | DECIMAL(10,4) | 上次触发时的基差值 |
| alert_count | INT | 预警次数 |
| first_alert_at | DATETIME | 首次预警时间 |
| last_alert_at | DATETIME | 最近预警时间 |
| cleared_at | DATETIME | 上次清零时间 |

### 3.6 basis_alert_history（基差预警历史 — 持久保存）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| user_id | INT | 外键 → users.id |
| coin_name | VARCHAR(20) | 币种名称 |
| alert_type | ENUM('new','expand') | 预警类型（新机会 / 基差扩大） |
| basis_value | DECIMAL(10,4) | 触发时基差值 |
| alert_at | DATETIME | 预警时间 |

### 3.7 unhedged_alert_configs（非对冲机会预警配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| user_id | INT UNIQUE | 外键 → users.id，一对一 |
| sound_enabled | TINYINT(1) | 声音开关 |
| popup_enabled | TINYINT(1) | 弹窗开关 |
| lark_bot_id | INT | 外键 → lark_bots.id（可空） |

### 3.8 unhedged_alert_cooldown（非对冲机会预警频率控制 — 内存/Redis 也可）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| coin_name | VARCHAR(20) | 币种名称 |
| long_exchange | VARCHAR(20) | 做多交易所 |
| short_exchange | VARCHAR(20) | 做空交易所 |
| alert_type | VARCHAR(20) | 预警类型 |
| last_alert_at | DATETIME | 上次预警时间 |

---

## 4. 后端 API 设计

### 4.1 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/register | 注册（username, password, confirm_password） |
| POST | /api/auth/login | 登录（username, password），返回 JWT |
| POST | /api/auth/logout | 退出登录 |
| GET | /api/auth/me | 获取当前用户信息 |

### 4.2 资金费率排行榜

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/funding-rank | 获取6个榜单数据（query: start, end） |
| GET | /api/funding-rank/detail | 某币种资费差额明细（query: coin, longEx, shortEx, start, end） |
| POST | /api/funding-rank/calculator | 资费统计器（body: coin, longEx, shortEx, start, end） |

### 4.3 新上线币种

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/new-listing | 获取3个榜单数据 |

### 4.4 资费即将突破

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/funding-break | 获取即将突破列表 |

### 4.5 价格趋势

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/price-trend | 获取多头排列数据（query: period 可选） |

### 4.6 基差监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/basis-monitor | 获取当前预警列表 |

### 4.7 非对冲机会

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/unhedged | 获取当前非对冲机会列表 |

### 4.8 预警配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/alert/lark-bots | 获取 Lark 机器人列表 |
| POST | /api/alert/lark-bots | 新增 Lark 机器人 |
| PUT | /api/alert/lark-bots/:id | 修改 Lark 机器人 |
| DELETE | /api/alert/lark-bots/:id | 删除 Lark 机器人 |
| GET | /api/alert/post-investment | 获取投后监测列表 |
| POST | /api/alert/post-investment | 新增投后监测 |
| PUT | /api/alert/post-investment/:id | 修改投后监测 |
| PATCH | /api/alert/post-investment/:id/toggle | 开关投后监测 |
| GET | /api/alert/basis | 获取基差预警配置 |
| PUT | /api/alert/basis | 更新基差预警配置 |
| GET | /api/alert/basis/history | 获取基差预警历史 |
| POST | /api/alert/basis/clear | 清除预警记录+不看币种 |
| GET | /api/alert/unhedged | 获取非对冲预警配置 |
| PUT | /api/alert/unhedged | 更新非对冲预警配置 |
| PUT | /api/settings/theme | 切换主题 |
| PUT | /api/settings/notification | 更新全局声音/弹窗开关 |

---

## 5. WebSocket 设计

### 连接地址
```
ws://localhost:8000/ws?token={jwt_token}  # 已登录用户（含预警推送）
ws://localhost:8000/ws                     # 未登录用户（仅数据推送）
```

### 推送频道与频率

| 频道 | 频率 | 数据内容 |
|------|------|----------|
| `basis_monitor` | 3秒 | 基差监控预警列表 |
| `unhedged` | 3秒 | 非对冲机会列表 |
| `funding_break` | 5秒 | 资费即将突破列表（基差+资费） |
| `spread_update` | 1分钟 | 资费排行榜开差数据 |
| `new_listing` | 5分钟 | 新上线币种数据 |
| `price_trend` | 10分钟 | 价格趋势数据 |
| `funding_rank` | 1小时 | 资费排行榜资费数据 |
| `alert_notification` | 实时 | 个人预警通知（投后监测、基差预警、非对冲预警） |

### 消息格式
```json
{
  "channel": "basis_monitor",
  "data": { ... },
  "timestamp": 1710000000
}
```

---

## 6. 定时任务调度

### 数据共享架构
基差监控、非对冲机会、投后监测共享同一个 API 调用结果，避免重复请求。

```
[3秒定时任务]
    │
    ├── 调用自有 API（BYBIT多 BN空）
    ├── 调用自有 API（OKX多 BN空）
    │
    ├──→ 基差监控引擎处理
    ├──→ 非对冲机会引擎处理
    ├──→ 投后监测引擎处理
    │
    └──→ WebSocket 推送
```

### 任务清单

| 频率 | 任务 | 数据源 |
|------|------|--------|
| 3秒 | 基差监控 + 非对冲机会 + 投后监测 | 自有 API |
| 5秒 | 资费即将突破结算周期 | 自有 API + 交易所资费上限 |
| 1分钟 | 资费排行榜开差刷新 | 交易所实时价格 API |
| 5分钟 | 新上线币种数据更新 | 交易所 K 线 API |
| 10分钟 | 价格趋势均线计算 | 币安 K 线 API |
| 1小时 | 资费排行榜资费数据刷新 | 交易所历史资费 API |
| 用户自定义 | 基差预警数据库清零 | 内部定时 |

---

## 7. 交易所 API 封装

### 7.1 Binance

| 接口 | 用途 |
|------|------|
| GET /fapi/v1/fundingRate | 历史资金费率 |
| GET /fapi/v1/fundingInfo | 资费上限/下限、结算周期 |
| GET /fapi/v1/klines | K线数据（均线计算、新币涨幅） |
| GET /fapi/v1/ticker/price | 实时价格 |
| GET /fapi/v1/openInterest | 持仓量（OI） |
| GET /fapi/v1/exchangeInfo | 所有交易对信息 |

### 7.2 OKX

| 接口 | 用途 |
|------|------|
| GET /api/v5/public/funding-rate-history | 历史资金费率 |
| GET /api/v5/public/funding-rate | 当前资金费率及上下限 |
| GET /api/v5/market/candles | K线数据 |
| GET /api/v5/market/ticker | 实时价格 |

### 7.3 Bybit

| 接口 | 用途 |
|------|------|
| GET /v5/market/funding/history | 历史资金费率 |
| GET /v5/market/tickers | 实时价格 + 资费信息 |
| GET /v5/market/kline | K线数据 |

---

## 8. 核心计算逻辑

### 8.1 资费正负处理（全局统一）
```
做多方实际资费 = -originLongFundingRate
  （原始费率为负 → 做多收资费，实际为正）
做空方实际资费 = originShortFundingRate
  （原始费率为负 → 做空付资费，实际为负）
资费差 = 做多方实际资费 - 做空方实际资费
```

### 8.2 开差计算
```
开差 = (做空方价格 - 做多方价格) / 做空方价格
```

### 8.3 基差
```
基差 = API 返回的 shortPremium / longPremium 字段
     = (标记价格 - 指数价格) / 指数价格
```

### 8.4 多头排列判定
```
实时价格 > MA20 > MA60 > MA120 → 多头排列
```

---

## 9. 开发阶段规划

### 第一阶段：基础架构
- [ ] 后端 FastAPI 项目初始化
- [ ] 前端 React + Vite 项目初始化
- [ ] MySQL 数据库建表
- [ ] JWT 认证
- [ ] WebSocket 基础通信
- [ ] 用户注册/登录/主题切换

### 第二阶段：核心数据模块
- [ ] 交易所 API 封装（Binance、OKX、Bybit）
- [ ] 自有 API 封装
- [ ] 资金费率排行榜（6个榜单 + 开差 + 资费统计器）
- [ ] 新上线币种（3个榜单）

### 第三阶段：实时监控模块
- [ ] 资费即将突破结算周期
- [ ] 基差监控（3秒轮询 + 预警逻辑）
- [ ] 非对冲机会（2种类型）
- [ ] 价格趋势（均线计算）

### 第四阶段：预警系统
- [ ] Lark 机器人管理
- [ ] 投后监测（配置 + 3秒监测）
- [ ] 基差预警（个性化配置 + 历史列表）
- [ ] 非对冲机会预警
- [ ] 声音/弹窗通知

### 第五阶段：优化
- [ ] 亮色/暗色主题完善
- [ ] 性能优化（数据缓存、请求合并）
- [ ] 错误处理与重连机制
