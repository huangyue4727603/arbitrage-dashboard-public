# Arbitrage Dashboard - 加密货币套利仪表盘

监控 Binance / OKX / Bybit 三大交易所的资金费率、基差、价差等数据，提供套利机会发现和预警功能。

## 功能一览

| 模块 | 说明 |
|------|------|
| 资费排行 | 6 个交易所配对的资金费率差排行榜 |
| 新上线币种 | 近 30 天内新上线的 USDT 永续合约 |
| 资费突破 | 实时资费即将突破结算上限的币种 |
| 价格趋势 | 基于 MA20/60/120 的多头排列分析 |
| 基差监控 | 基差异常预警，自动检测套利机会 |
| 非对冲机会 | 资费差套利和价差机会检测 |
| 预警配置 | 自定义预警规则，支持声音/弹窗/飞书通知 |

## 技术栈

- **后端**：Python 3.9+ / FastAPI / SQLAlchemy 2.0 (async) / APScheduler
- **前端**：React 19 / TypeScript / Ant Design 6 / Vite / Zustand
- **数据库**：MySQL 5.7+
- **实时通信**：WebSocket

---

## 部署指南

下面一步一步教你从零部署到服务器上。

### 第一步：准备服务器环境

你需要一台 Linux 服务器（推荐 Ubuntu 20.04 或 CentOS 7+），以下操作都在服务器上执行。

#### 1.1 安装 Python 3.9+

```bash
# Ubuntu
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# CentOS
sudo yum install -y python3 python3-pip

# 验证版本（需要 3.9 或更高）
python3 --version
```

#### 1.2 安装 Node.js 18+

```bash
# 使用 NodeSource 安装（Ubuntu / CentOS 通用）
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs    # Ubuntu
# 或
sudo yum install -y nodejs    # CentOS

# 验证
node --version
npm --version
```

#### 1.3 安装 MySQL 5.7+

如果你已经有 MySQL（比如云数据库 RDS），跳过这步，直接用你的连接信息。

```bash
# Ubuntu
sudo apt install -y mysql-server
sudo systemctl start mysql
sudo systemctl enable mysql

# 设置 root 密码
sudo mysql_secure_installation
```

安装完成后，创建一个数据库：

```bash
# 登录 MySQL
mysql -u root -p

# 在 MySQL 命令行中执行：
CREATE DATABASE arbitrage DEFAULT CHARSET utf8mb4;
CREATE USER 'arb_user'@'%' IDENTIFIED BY '你的密码';
GRANT ALL PRIVILEGES ON arbitrage.* TO 'arb_user'@'%';
FLUSH PRIVILEGES;
EXIT;
```

> 记住你设置的 **数据库名**、**用户名**、**密码**，后面要用。

#### 1.4 安装 Git

```bash
# Ubuntu
sudo apt install -y git

# CentOS
sudo yum install -y git
```

---

### 第二步：下载代码

```bash
# 在服务器上选一个目录
cd /home

# 下载代码
git clone https://github.com/johnnyfirst1/arbitrage-dashboard-public.git

# 进入项目目录
cd arbitrage-dashboard-public
```

---

### 第三步：配置后端

#### 3.1 创建 Python 虚拟环境

```bash
cd /home/arbitrage-dashboard-public/backend

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境（每次操作后端都要先激活）
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

> 如果 pip install 很慢，可以换国内源：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

#### 3.2 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑配置
vi .env
```

把 `.env` 的内容改成你自己的信息：

```env
# 数据库连接
# 格式：mysql+aiomysql://用户名:密码@数据库地址:端口/数据库名?charset=utf8mb4
DATABASE_URL=mysql+aiomysql://arb_user:你的密码@127.0.0.1:3306/arbitrage?charset=utf8mb4

# JWT 密钥（随便写一串复杂的字符串，用于登录加密）
JWT_SECRET=my-super-secret-key-abc123xyz

# 以下两项不用改
JWT_ALGORITHM=HS256
JWT_EXPIRE_DAYS=7

# 套利数据 API 地址（找项目提供者要这个地址）
ARBITRAGE_API_URL=http://你的套利API地址:9000
```

**各项说明：**

| 配置项 | 说明 | 示例 |
|--------|------|------|
| DATABASE_URL | MySQL 连接地址 | `mysql+aiomysql://arb_user:pass123@127.0.0.1:3306/arbitrage?charset=utf8mb4` |
| JWT_SECRET | 登录加密密钥，随便填一串长字符 | `abc123-my-secret-key-xyz` |
| ARBITRAGE_API_URL | 套利数据源 API 地址 | `http://1.2.3.4:9000` |

#### 3.3 测试后端能否启动

```bash
# 确保在 backend 目录，虚拟环境已激活
cd /home/arbitrage-dashboard-public/backend
source venv/bin/activate

# 启动后端
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

看到类似下面的输出就是成功了：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

> 第一次启动时，程序会**自动创建所有数据库表**，不需要手动建表。

按 `Ctrl+C` 停止，继续下一步。

---

### 第四步：配置前端

```bash
cd /home/arbitrage-dashboard-public/frontend

# 安装依赖
npm install
```

> 如果 npm install 很慢，可以换淘宝源：
> ```bash
> npm install --registry https://registry.npmmirror.com
> ```

#### 4.1 打包前端（生产部署）

```bash
# 打包
npm run build
```

打包完成后会生成 `dist` 目录，里面是静态文件。

---

### 第五步：正式部署（让程序一直运行）

开发测试时可以直接用上面的命令启动。正式部署需要让程序在后台持续运行，即使关掉终端也不会停止。

#### 方式一：使用 systemd（推荐）

##### 5.1 创建后端服务

```bash
sudo vi /etc/systemd/system/arb-backend.service
```

粘贴以下内容：

```ini
[Unit]
Description=Arbitrage Dashboard Backend
After=network.target mysql.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/arbitrage-dashboard-public/backend
Environment=PATH=/home/arbitrage-dashboard-public/backend/venv/bin:/usr/bin
ExecStart=/home/arbitrage-dashboard-public/backend/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

##### 5.2 启动后端服务

```bash
# 重新加载配置
sudo systemctl daemon-reload

# 启动
sudo systemctl start arb-backend

# 设置开机自启
sudo systemctl enable arb-backend

# 查看状态（应该显示 active (running)）
sudo systemctl status arb-backend

# 查看日志（排查问题用）
sudo journalctl -u arb-backend -f
```

##### 5.3 安装 Nginx（用来访问前端页面）

```bash
# Ubuntu
sudo apt install -y nginx

# CentOS
sudo yum install -y nginx
```

##### 5.4 配置 Nginx

```bash
sudo vi /etc/nginx/sites-available/arbitrage
```

> CentOS 没有 sites-available 目录，直接编辑 `/etc/nginx/conf.d/arbitrage.conf`

粘贴以下内容：

```nginx
server {
    listen 80;
    server_name _;  # 如果有域名，把 _ 改成你的域名

    # 前端静态文件
    root /home/arbitrage-dashboard-public/frontend/dist;
    index index.html;

    # 前端路由（单页应用）
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # WebSocket 代理
    location /ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

##### 5.5 启用 Nginx 配置

```bash
# Ubuntu：创建软链接
sudo ln -s /etc/nginx/sites-available/arbitrage /etc/nginx/sites-enabled/
# 删除默认配置（避免冲突）
sudo rm -f /etc/nginx/sites-enabled/default

# 测试配置是否正确
sudo nginx -t

# 启动 Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

#### 方式二：使用 Screen（简单方式）

如果不想配置 systemd，可以用 screen 简单地后台运行：

```bash
# 安装 screen
sudo apt install -y screen  # Ubuntu
sudo yum install -y screen  # CentOS

# 启动后端
screen -S backend
cd /home/arbitrage-dashboard-public/backend
source venv/bin/activate
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 按 Ctrl+A 然后按 D 退出 screen（程序继续在后台运行）

# 如果不用 Nginx，可以直接启动前端开发服务器
screen -S frontend
cd /home/arbitrage-dashboard-public/frontend
npx vite --host 0.0.0.0
# 按 Ctrl+A 然后按 D 退出 screen

# 重新进入 screen 查看
screen -r backend
screen -r frontend
```

---

### 第六步：访问你的仪表盘

部署完成后，在浏览器打开：

- **使用 Nginx（推荐）**：`http://你的服务器IP`
- **使用 Screen 开发模式**：`http://你的服务器IP:5173`

> 注意：启动后需要等 1-2 分钟，后端才会拉取到第一批实时数据。

---

## 代理配置（可选）

如果你的服务器在国内，访问 Binance/OKX/Bybit API 可能需要代理。在 `.env` 中添加：

```env
HTTP_PROXY=http://127.0.0.1:你的代理端口
```

如果你的服务器在海外（比如香港、新加坡），通常不需要配代理。

---

## 常见问题

### Q: 启动后端报 "Can't connect to MySQL server"

检查：
1. MySQL 是否在运行：`systemctl status mysql`
2. `.env` 里的数据库地址、用户名、密码是否正确
3. 如果用的是云数据库，检查安全组是否放行了 3306 端口

### Q: 前端页面打开是空白

检查：
1. 是否执行了 `npm run build`
2. Nginx 配置中 `root` 路径是否指向 `frontend/dist`
3. 执行 `sudo nginx -t` 检查配置是否有语法错误

### Q: 页面能打开，但没有数据

1. 后端是否正常运行：`curl http://127.0.0.1:8000/api/health`
2. 启动后需要等 1-2 分钟才有实时数据
3. 检查 `.env` 中的 `ARBITRAGE_API_URL` 是否正确

### Q: pip install 报错

```bash
# 如果提示缺少 mysql 开发包
sudo apt install -y libmysqlclient-dev   # Ubuntu
sudo yum install -y mysql-devel          # CentOS

# 如果提示缺少 Python 开发包
sudo apt install -y python3-dev          # Ubuntu
sudo yum install -y python3-devel        # CentOS
```

### Q: npm install 报错

```bash
# 清除缓存重试
rm -rf node_modules package-lock.json
npm install
```

---

## 常用运维命令

```bash
# 查看后端状态
sudo systemctl status arb-backend

# 重启后端
sudo systemctl restart arb-backend

# 查看后端实时日志
sudo journalctl -u arb-backend -f

# 重启 Nginx
sudo systemctl restart nginx

# 更新代码
cd /home/arbitrage-dashboard-public
git pull
# 后端：重启服务
sudo systemctl restart arb-backend
# 前端：重新打包 + 重启 Nginx
cd frontend && npm run build
sudo systemctl restart nginx
```

---

## 项目结构

```
arbitrage-dashboard-public/
├── backend/                  # 后端代码
│   ├── app/
│   │   ├── main.py           # 入口文件
│   │   ├── config.py         # 配置读取
│   │   ├── database.py       # 数据库连接
│   │   ├── models/           # 数据库表定义（自动建表）
│   │   ├── routers/          # API 接口
│   │   ├── services/         # 业务逻辑
│   │   ├── schedulers/       # 定时任务
│   │   ├── utils/            # 工具函数
│   │   └── websocket/        # WebSocket 管理
│   ├── requirements.txt      # Python 依赖
│   ├── .env.example          # 环境变量模板
│   └── .env                  # 环境变量（需自己创建，不要上传）
├── frontend/                 # 前端代码
│   ├── src/
│   │   ├── pages/            # 页面组件
│   │   ├── api/              # API 调用
│   │   ├── hooks/            # 自定义 Hooks
│   │   ├── stores/           # 状态管理
│   │   └── components/       # 公共组件
│   ├── package.json          # Node.js 依赖
│   └── vite.config.ts        # Vite 配置
├── HANDOVER.md               # 技术交接文档（开发者看）
├── REQUIREMENTS.md           # 功能需求文档
└── README.md                 # 本文件
```

---

## License

MIT
