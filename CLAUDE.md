# geo-checker

GEO (Generative Engine Optimization) 分析工具 — AI 搜尋引擎可見性檢測。
FastAPI + Python 3.11+ + Docker，部署於 VPS ranran.tw（gc.ranran.tw）。

## 繼承聲明

本專案繼承全域 `~/.claude/CLAUDE.md` 的所有規則。
以下為本專案特有的補充規則。

## 撞牆停手（專案特有情境）

- AI fetcher / parser 連續兩次失敗且錯誤相同（可能是目標 AI 引擎 API 變更）
- Docker build 或 deploy.sh 連續兩次失敗

撞牆後停手，整理問題說明，不得繼續改 code。

## 安全紅線

### Credential 保護
- `.env` 含 API key 等敏感資訊，禁止 commit
- Traefik TLS 設定（abd-network）不可隨意修改

### 部署
- 部署目標：VPS ranran.tw（139.180.201.136），`ssh ranran`
- 路徑：`/opt/geo-checker/`，使用 `deploy.sh`
- Docker container，Traefik reverse proxy（gc.ranran.tw）
- `./data/` volume 含分析結果，**禁止刪除**
- 同 VPS 有其他 ABD 工具（abd-network），注意不要影響

### 服務保護
- 這是**面向內部使用**的分析工具，修改 AI 引擎 fetcher/parser 視為 **YELLOW**
- mem_limit 1536m 已設定，不可大幅調高

## 開發指令

```bash
# 本地開發
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# Docker
docker compose up -d

# 部署（VPS）
ssh ranran "cd /opt/geo-checker && bash deploy.sh"
```

## 技術棧

| 層 | 技術 |
|----|------|
| 後端 | FastAPI + Python 3.11+ |
| AI 引擎 | fetcher + parser（多引擎支援） |
| 報告 | audit + report 模組 |
| 容器 | Docker + Traefik |

## 專案結構

```
geo-checker/
├── app/            # Web API（FastAPI routes）
├── src/            # 核心邏輯
│   ├── ai/         # AI 引擎相關
│   ├── fetcher/    # 資料擷取
│   ├── parser/     # 解析器
│   ├── geo/        # GEO 分析
│   ├── seo/        # SEO 分析
│   ├── audit/      # 審計模組
│   └── report/     # 報告產生
├── data/           # 分析結果儲存
└── deploy.sh       # 部署腳本
```
