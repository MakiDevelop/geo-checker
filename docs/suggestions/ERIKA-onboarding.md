# ERIKA Onboarding - geo-checker

**Date**: 2026-01-31
**From**: Claude (Orchestrator)
**To**: ERIKA
**Status**: Action Required

---

## Repo 資訊

- **Repo**: `git@github.com:MakiDevelop/ABD.git`
- **Path**: `geo-checker/` (monorepo 內的子專案)
- **Branch**: `main`

## 你的權限

- **Readonly** - 可 clone、pull、讀取所有檔案
- 修改/commit/push 由 Claude、Codex、Gemini 負責

## 專案簡介

GEO Checker 是一個 GEO (Generative Engine Optimization) 內容評分工具，用於評估文章在 AI 搜尋引擎中的表現潛力。

## 你的職責

1. **通知** - 當有決策型 RFC 需要 Maki 審批時，透過 LINE 即時通知
2. **接收決策** - 接收 Maki 的決策（批准/退回），回報給 Claude
3. **每日彙整** - 知會型 RFC、進度、SOP 進每日彙整

## 協作文件

- `docs/AI-COLLABORATION-PROTOCOL.md` - 協作規則
- `docs/decision-log.md` - 決策紀錄
- `docs/suggestions/` - 提案草稿（AI↔AI 溝通）
- `docs/rfc/` - 正式 RFC

## 通知規則

| 類型 | 通知方式 |
|-----|---------|
| 決策型 RFC（需選 A/B） | LINE 即時 |
| 知會型 RFC / 進度 / SOP | 每日彙整 |
| 失敗/阻塞/異常 | LINE 即時 |

節流：同類事件 10 分鐘內最多 1 則

## 下一步

1. Clone repo: `git clone git@github.com:MakiDevelop/ABD.git`
2. 閱讀 `geo-checker/docs/AI-COLLABORATION-PROTOCOL.md` 了解協作規則
3. 確認可存取此 repo
4. 回覆此文件確認 onboarding 完成

---

*此文件由 Claude 建立，請 ERIKA 確認收到後更新 Status 為 Acknowledged*
