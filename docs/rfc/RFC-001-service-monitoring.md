# RFC-001: geo-checker 服務狀態監控

**Date**: 2026-01-31
**From**: Claude (Orchestrator)
**Status**: Approved
**Type**: 決策型（需選 A/B/C）
**Decision**: A（ERIKA VPS cron job）

---

## 背景

geo-checker 服務部署於 https://gc.ranran.tw，需要監控服務狀態，並在下線或嚴重故障時由 ERIKA 即時通知 Maki。

## 選項

### A) ERIKA VPS cron job（推薦）

ERIKA 所在的 VPS 設置 cron job，定期 ping 健康檢查端點。

```
優點：
- 完全自主控制
- 無外部依賴
- ERIKA 直接感知狀態，可即時 LINE 通知

缺點：
- 需要在 ERIKA VPS 部署腳本
- 單點監控（若 VPS 也掛則無法通知）

實作：
- 每 5 分鐘檢查 https://gc.ranran.tw/health
- 連續 2 次失敗 → LINE 通知
- 恢復後 → LINE 通知
```

### B) 外部監控服務 + Webhook

使用 UptimeRobot（免費）或類似服務，故障時 webhook 觸發 ERIKA。

```
優點：
- 多點監控（更可靠）
- 不佔用 ERIKA 資源

缺點：
- 依賴第三方服務
- 需要設置 webhook endpoint

實作：
- UptimeRobot 免費方案（5 分鐘間隔）
- Webhook → ERIKA API → LINE 通知
```

### C) 混合方案

ERIKA cron 為主 + UptimeRobot 為備援。

```
優點：
- 雙重保障

缺點：
- 設置較複雜
- 可能重複通知（需去重）
```

## 前置需求

1. **Health endpoint 已存在但未部署**
   - 程式碼：`app/api/v1/endpoints/health.py` ✓
   - 路徑：`/api/v1/health`
   - 線上狀態：404（`app/api/` 尚未 commit/部署）

2. **需先部署 API 模組**
   - commit `app/api/` 目錄
   - 重新部署服務

3. **臨時替代方案**
   - 根目錄 `/` 目前返回 200
   - 可先用此作為基本存活檢查

## 請決策

請選擇 A / B / C，或提出其他方案。

---

*此 RFC 由 Claude 建立，等待 Maki 決策*
