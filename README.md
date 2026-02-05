# SEO + GEO Checker

## Project Positioning

This project targets **GEO (Generative Engine Optimization)** as its primary market.

The core goal is to evaluate whether content can be:
- correctly understood by AI / LLM systems,
- accurately summarized and referenced,
- and not misinterpreted in AI-driven search or answer generation.

Traditional SEO signals are treated **only as structural and readability foundations**.
They are **not optimization goals** of this project.

In short:

> SEO helps content get found.  
> GEO ensures content gets interpreted correctly.

CLI-first skeleton for a local SEO + GEO (Generative Engine Optimization) checker.

## Usage

```bash
python -m src.main run <url-or-path>
```

This project currently outputs placeholders only.

## Web UI / Web 介面

Start the server (FastAPI) and open `http://localhost:8000`.
啟動 FastAPI 伺服器後，開啟 `http://localhost:8000`。

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Parsing Setup / 解析環境

spaCy model is required for entity extraction.
Entity 抽取需要安裝 spaCy model。

```bash
python -m spacy download en_core_web_sm
```

## Architecture / 架構

This project is CLI-first and fully local. It only performs analysis and risk hints.
本專案以 CLI 為主、完全在本地端執行，只做分析與風險提示。

## Data Flow / 資料流

1. `src/main.py` parses CLI args and orchestrates the flow.
   `src/main.py` 負責解析參數並串接流程。
2. `src/fetcher/html_fetcher.py` retrieves raw HTML from a URL or file.
   `src/fetcher/html_fetcher.py` 從 URL 或檔案取得原始 HTML。
3. `src/parser/content_parser.py` extracts main content and basic structure.
   `src/parser/content_parser.py` 抽取主要內容與基本結構。
4. `src/seo/seo_checker.py` runs mechanical SEO checks.
   `src/seo/seo_checker.py` 執行可機械驗證的 SEO 規則檢查。
5. `src/geo/geo_checker.py` runs AI/LLM readability and risk heuristics.
   `src/geo/geo_checker.py` 執行 AI/LLM 可理解性與風險 heuristic。
6. `src/ai/ai_simulator.py` optionally simulates a local LLM summary.
   `src/ai/ai_simulator.py` 可選，用於本地 LLM 摘要模擬。
7. `src/report/formatter.py` formats results for CLI/JSON/Markdown output.
   `src/report/formatter.py` 統一輸出格式（CLI/JSON/Markdown）。
