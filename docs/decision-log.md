# Decision Log

**用途**：記錄所有技術決策，供回溯與審計
**規則**：只新增，不修改歷史條目

---

## 格式

```
### [YYYY-MM-DD] 決策標題

**背景**：為什麼需要這個決策
**選項**：
- A) ...
- B) ...
- C) ...

**決策**：選 X
**理由**：...
**影響**：...
**決策者**：Maki / Claude / Gemini / Codex / ERIKA
```

---

*新決策請追加在此文件底部*

---

### [2026-01-31] ERIKA 權限設定

**背景**：啟動五位一體模式，需定義各角色對 repo 的操作權限

**選項**：
- A) ERIKA 有完整 read/write/push 權限
- B) ERIKA 只有 readonly 權限，修改由 Claude/Codex/Gemini 負責
- C) 所有 AI 都只有 readonly，commit 全由人類執行

**決策**：選 B

**理由**：
- ERIKA 定位為「用戶端代理、執行、監控」，主要負責觀察與回報
- 修改與 commit 權限集中於 Claude（總指揮）、Codex（實作）、Gemini（調查）
- 降低意外修改風險，維持清晰的責任分工

**影響**：
- ERIKA 可 clone、pull、read 所有檔案
- ERIKA 無法直接 push，需透過其他 AI 或人類提交變更
- 所有 AI→Human 通知仍由 ERIKA 負責（LINE 等管道）

**決策者**：Maki

---

### [2026-01-31] RFC-001 服務監控方式

**背景**：geo-checker (https://gc.ranran.tw) 需要服務狀態監控，故障時由 ERIKA 通知

**選項**：
- A) ERIKA VPS cron job 定期檢查 health endpoint
- B) UptimeRobot 外部監控 + Webhook 觸發 ERIKA
- C) 混合方案（A+B）

**決策**：選 A

**理由**：
- 完全自主控制，無外部依賴
- ERIKA 直接感知狀態，可即時 LINE 通知
- 實作簡單，符合現有架構

**影響**：
- ERIKA VPS 需部署監控腳本
- 每 5 分鐘檢查 /api/v1/health
- 連續 2 次失敗 → LINE 即時通知
- 恢復後 → LINE 通知

**決策者**：Maki

---

### [2026-01-31] 部署 API 模組

**背景**：app/api/ 目錄含 health、analyze、jobs endpoints，尚未 commit

**決策**：立即 commit 並部署

**影響**：
- 新增 /api/v1/health（健康檢查）
- 新增 /api/v1/analyze（非同步分析）
- 新增 /api/v1/jobs/{id}（查詢結果）

**決策者**：Maki
