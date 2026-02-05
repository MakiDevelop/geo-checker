# AI Collaboration Protocol - 五位一體

**版本**：1.0
**適用**：本專案所有 AI agents

---

## 參與者

| 角色 | 職責 |
|-----|------|
| **Maki** | 產品與技術最終決策者 |
| **Claude** | 總指揮（架構、拆解、整合） |
| **Gemini** | 技術調查與風險顧問 |
| **Codex** | 實作與 code review 專家 |
| **ERIKA** | 用戶端代理、執行、監控 |

---

## 溝通管道

### AI↔AI（自動）
- `docs/suggestions/` - 提案草稿
- `docs/rfc/` - 正式 RFC 文件
- `docs/poc/` - 技術驗證
- Git commit / PR review

### AI→Human（僅決策點）
- LINE 即時通知：僅「需選 A/B」的決策型 RFC
- 每日彙整：知會型 RFC、進度、SOP

---

## RFC 工作流

```
1. [Draft] → docs/suggestions/
2. [Review] → AI 互評、修訂
3. [RFC] → docs/rfc/RFC-NNN-title.md
4. [Ready] → 標記 Status: Ready
5. [Notify] → LINE 通知（僅決策型）
6. [Decision] → Human 批准/退回
7. [Record] → docs/decision-log.md
```

---

## 通知規則（RFC-002 + 門檻）

| 類型 | 通知方式 |
|-----|---------|
| 決策型 RFC（需選 A/B） | LINE 即時 |
| 知會型 RFC / 進度 / SOP | 每日彙整 |
| ETL/cleanup 成功 | 靜默 |
| 失敗/阻塞/異常 | LINE 即時 |

節流：同類事件 10 分鐘內最多 1 則
退避：429 後 30 分鐘不重試

---

## 啟動條件

在專案中說「啟動五位一體模式」即可啟動本協定。
