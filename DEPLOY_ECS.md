# ECS 部署清单（含指数成分抓取）

> 目标机器：`ecs-user@47.239.12.8`（`ssh ecs`）

## 1. 上传代码

本机执行：
```bash
rsync -avz --exclude='node_modules' --exclude='venv' --exclude='__pycache__' --exclude='.git' \
  /Users/imqiyue/projects/arbitrage-dashboard-aitbot/ ecs:/home/ecs-user/arbitrage-dashboard-aitbot/
```

## 2. 后端依赖（ECS）

```bash
ssh ecs <<'EOF'
cd ~/arbitrage-dashboard-aitbot/backend
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install playwright greenlet requests
python3 -m playwright install chromium
python3 -m playwright install-deps chromium  # 装系统依赖（需要 sudo 才能装；如果失败用下面手动）
EOF
```

如果 `install-deps` 报权限错误，手动装一次：
```bash
ssh ecs 'sudo apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2'
```

## 3. .env

```bash
ssh ecs 'cat > ~/arbitrage-dashboard-aitbot/backend/.env <<EOF
DATABASE_URL=mysql+aiomysql://dfsland:u49D3yElft74@rm-j6clxb631g9y6meobzo.mysql.rds.aliyuncs.com:3306/dfs_network?charset=utf8mb4
JWT_SECRET=replace-me-prod-secret-string
JWT_ALGORITHM=HS256
JWT_EXPIRE_DAYS=7
ARBITRAGE_API_URL=http://2.57.215.107:9000
EOF'
```

## 4. systemd 服务（后端常驻）

```bash
ssh ecs 'sudo tee /etc/systemd/system/arbitrage-backend.service > /dev/null <<EOF
[Unit]
Description=Arbitrage Dashboard Backend
After=network.target

[Service]
Type=simple
User=ecs-user
WorkingDirectory=/home/ecs-user/arbitrage-dashboard-aitbot/backend
Environment="TZ=Asia/Shanghai"
ExecStart=/home/ecs-user/arbitrage-dashboard-aitbot/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now arbitrage-backend
sudo systemctl status arbitrage-backend --no-pager'
```

## 5. 前端构建 + Nginx

```bash
ssh ecs <<'EOF'
cd ~/arbitrage-dashboard-aitbot/frontend
npm install
npm run build
sudo cp -r dist /var/www/arbitrage
EOF
```

Nginx site (`/etc/nginx/sites-available/arbitrage`)：
```nginx
server {
  listen 80;
  server_name _;
  location /arbitrage/ {
    alias /var/www/arbitrage/;
    try_files $uri $uri/ /arbitrage/index.html;
  }
  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
  location /ws {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
  }
}
```

```bash
ssh ecs 'sudo ln -sf /etc/nginx/sites-available/arbitrage /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx'
```

## 6. 冒烟测试

```bash
ssh ecs 'curl -s http://localhost:8000/api/funding-rank/coins | head -c 200'
ssh ecs 'curl -s http://localhost:8000/api/funding-rank/index-overlap | head -c 200'
ssh ecs 'sudo journalctl -u arbitrage-backend -n 50 --no-pager | grep -i "index-constituents\|index_const"'
```

## 7. 指数成分跑通后验证

启动后大约 5 分钟内会自动检测新币入队并开始抓取。检查：
```bash
ssh ecs 'mysql -h rm-j6clxb631g9y6meobzo.mysql.rds.aliyuncs.com -u dfsland -p"u49D3yElft74" dfs_network -e \
  "SELECT exchange, COUNT(*) FROM arb_index_constituents GROUP BY exchange"'
```

## Bybit Selector 调试

第一次跑 Bybit 抓取可能拿不到数据（DOM 结构未知）。在 ECS 上手动跑一次：
```bash
ssh ecs 'cd ~/arbitrage-dashboard-aitbot/backend && source venv/bin/activate && python3 -c "
import asyncio
from app.services.index_constituents import fetch_bybit
print(asyncio.run(fetch_bybit(\"BTC\")))
"'
```

如果返回 None 或空，需要：
1. 在 ECS 上用 `playwright codegen` 录制实际页面
2. 或者手动改 `app/services/index_constituents.py` 里 `fetch_bybit` 的 selector

## 时区注意

ECS 必须设置 `TZ=Asia/Shanghai`（systemd unit 已包含），保证 `datetime.now()` 与本地时间和数据库时间一致。

## 重启 / 更新

```bash
# 重启
ssh ecs 'sudo systemctl restart arbitrage-backend'

# 拉新代码 + 重启
rsync -avz --exclude='node_modules' --exclude='venv' --exclude='__pycache__' --exclude='.git' \
  /Users/imqiyue/projects/arbitrage-dashboard-aitbot/ ecs:/home/ecs-user/arbitrage-dashboard-aitbot/
ssh ecs 'cd ~/arbitrage-dashboard-aitbot/frontend && npm run build && sudo cp -r dist/* /var/www/arbitrage/ && sudo systemctl restart arbitrage-backend'
```
