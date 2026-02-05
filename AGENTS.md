# AGENTS.md
## SEO + GEO Checker 專案骨架建立指示

本文件是給 AI agents（例如 Codex、Claude、Cursor、Copilot）使用的**唯一權威指示**。
請嚴格依照本文件建立專案骨架，不要自行發揮、不加功能、不提前優化。

---

## 一、專案目標（請先理解再動手）

本專案目標是建立一個 **可於本地端執行的 SEO + GEO（Generative Engine Optimization）檢查器**，
用來檢查單一 URL 或 HTML 文件：
- 傳統 SEO 技術健康度
- AI / LLM 是否容易正確理解內容
- 內容是否存在被 AI 誤解或 hallucination 的風險

**V1 僅做分析與檢查，不做內容生成、不做排名預測。**

---


## 二、技術與架構原則（必須遵守）

### Primary Market & Design Constraint（最高優先級）

本專案的 **Primary Market** 為  
**GEO（Generative Engine Optimization）**。

本專案關注的核心問題是：
- 內容是否能被 AI / LLM 正確理解
- 是否能被正確摘要與轉述
- 是否存在被 AI 誤解或敘事漂移的風險

傳統 SEO 在本專案中僅視為：
- 結構完整性
- 內容可讀性
- 技術衛生條件

**SEO 並非本專案的優化目標。**

#### 明確禁止事項
- 禁止任何以「搜尋排名提升」為目的的設計
- 禁止引入關鍵字排名、流量預估、CPC、SERP 分析
- 禁止以搜尋引擎演算法行為作為成功指標

若設計決策在 GEO 與 SEO 之間產生衝突，  
**一律以 GEO 為優先。**

1. **CLI-first**
   - 不做 Web UI
   - 所有功能可由 CLI 觸發

2. **本地端優先**
   - 不強制依賴外部 API
   - LLM 僅使用本地模型（可選）

3. **可解釋性**
   - 不產生黑箱總分
   - 每個檢查結果必須對應明確 rule 或 heuristic

4. **模組邊界清楚**
   - SEO、GEO、AI 模擬彼此獨立
   - 不混雜邏輯

---

## 三、請建立的專案目錄結構

請建立以下目錄與檔案結構：

seo-geo-checker/
├── README.md
├── AGENTS.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml          # 可先建立空檔
├── src/
│   ├── __init__.py
│   ├── main.py             # CLI 入口
│   ├── cli/
│   │   ├── __init__.py
│   │   └── run.py
│   ├── fetcher/
│   │   ├── __init__.py
│   │   └── html_fetcher.py
│   ├── parser/
│   │   ├── __init__.py
│   │   └── content_parser.py
│   ├── seo/
│   │   ├── __init__.py
│   │   └── seo_checker.py
│   ├── geo/
│   │   ├── __init__.py
│   │   └── geo_checker.py
│   ├── ai/
│   │   ├── __init__.py
│   │   └── ai_simulator.py
│   ├── rules/
│   │   ├── __init__.py
│   │   └── base.py
│   └── report/
│       ├── __init__.py
│       └── formatter.py
└── tests/
    └── test_smoke.py

---

## 四、各模組責任說明（不可違反）

### 1. main.py
- CLI 程式進入點
- 僅負責參數解析與流程組裝
- 不寫任何業務邏輯

### 2. fetcher/html_fetcher.py
- 負責抓取 HTML（URL 或本地檔案）
- 不做解析、不做清洗

### 3. parser/content_parser.py
- 從 HTML 中抽取主要內容
- 輸出乾淨文字與基本結構資訊

### 4. seo/seo_checker.py
- 傳統 SEO 規則檢查
- 僅處理可機械驗證的項目

### 5. geo/geo_checker.py
- AI 可理解性與語意風險檢查
- 使用 heuristic / rule-based 方法

### 6. ai/ai_simulator.py
- （可選）使用本地 LLM 進行摘要模擬
- 不得依賴雲端 API

### 7. report/formatter.py
- 統一輸出格式（CLI / JSON / Markdown）
- 不參與檢查邏輯

---

## 五、請建立的檔案內容（最低可執行）

### requirements.txt

請至少包含：

- requests
- beautifulsoup4
- lxml
- readability-lxml
- typer
- rich

LLM、NLP 套件先不要加，等下一階段再處理。

---

### Dockerfile（基礎即可）

- Base image：python:3.11-slim
- 複製 requirements.txt 並安裝
- 設定 WORKDIR 為 /app
- 預設 CMD 不需執行程式

---

### docker-compose.yml

- 單一 service：seo-geo-checker
- 掛載專案目錄
- 預留未來加 LLM container 的空間（註解即可）

---

## 六、禁止事項（非常重要）

AI agents **禁止做以下事情**：

- 不要實作實際 SEO 檢查邏輯
- 不要加入排名、流量、關鍵字建議
- 不要接任何外部 API
- 不要自動下載模型
- 不要新增 Web UI

只建立骨架與最低可跑結構。

---

## 七、完成定義（Done Definition）

以下條件全部成立，才算完成：

1. 專案可成功 build Docker image
2. CLI 可執行（即使只輸出 placeholder）
3. 目錄結構與模組邊界完全符合本文件
4. 不包含任何未指示的功能

---

結束後請停止，不要繼續延伸功能。
