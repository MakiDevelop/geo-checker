"""Content parsing utilities."""
from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from readability import Document

from src.config.settings import settings

try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False

try:
    import textstat
    TEXTSTAT_AVAILABLE = True
except ImportError:
    TEXTSTAT_AVAILABLE = False

try:
    import extruct
    EXTRUCT_AVAILABLE = True
except ImportError:
    EXTRUCT_AVAILABLE = False

# Thread-safe NLP model loading
_NLP = None
_NLP_LOCK = threading.Lock()
_NLP_AVAILABLE = True


def _detect_language(text: str) -> str:
    """Detect primary language of text based on character patterns.

    Returns:
        Language code: 'zh', 'ja', 'ko', 'en', or 'mixed'
    """
    if not text:
        return "en"

    # Count character types
    cjk_count = 0
    latin_count = 0

    for char in text[:1000]:  # Sample first 1000 chars
        code = ord(char)
        # CJK Unified Ideographs
        if 0x4E00 <= code <= 0x9FFF:
            cjk_count += 1
        # Hiragana/Katakana (Japanese specific)
        elif 0x3040 <= code <= 0x30FF:
            return "ja"
        # Hangul (Korean specific)
        elif 0xAC00 <= code <= 0xD7AF:
            return "ko"
        # Latin letters
        elif (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
            latin_count += 1

    total = cjk_count + latin_count
    if total == 0:
        return "en"

    cjk_ratio = cjk_count / total
    if cjk_ratio > 0.3:
        return "zh"  # Could be Chinese (Traditional or Simplified)

    return "en"


def _extract_cjk_entities(text: str) -> list[dict]:
    """Extract entities from CJK text using pattern matching.

    This is a fallback for when spaCy doesn't support the language well.
    Uses common patterns to identify potential entities.
    """
    entities = []

    # Chinese/Japanese patterns for organizations
    org_patterns = [
        r"[\u4e00-\u9fff]+(?:公司|集團|銀行|大學|學院|醫院|政府|委員會|協會|基金會|研究所|中心)",
        r"[\u4e00-\u9fff]+(?:会社|銀行|大学|研究所)",  # Japanese
    ]

    # Patterns for locations
    location_patterns = [
        r"[\u4e00-\u9fff]+(?:市|省|縣|區|國|州|島)",
        r"[\u4e00-\u9fff]+(?:市|県|区|国)",  # Japanese
    ]

    # Date patterns
    date_patterns = [
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{4}年\d{1,2}月",
        r"\d{4}年",
        r"\d{1,2}月\d{1,2}日",
    ]

    # Extract organizations
    for pattern in org_patterns:
        for match in re.finditer(pattern, text):
            entities.append({
                "text": match.group(),
                "label": "ORG",
                "source": "pattern"
            })

    # Extract locations
    for pattern in location_patterns:
        for match in re.finditer(pattern, text):
            entities.append({
                "text": match.group(),
                "label": "GPE",
                "source": "pattern"
            })

    # Extract dates
    for pattern in date_patterns:
        for match in re.finditer(pattern, text):
            entities.append({
                "text": match.group(),
                "label": "DATE",
                "source": "pattern"
            })

    # Deduplicate
    seen = set()
    unique_entities = []
    for ent in entities:
        key = (ent["text"], ent["label"])
        if key not in seen:
            seen.add(key)
            unique_entities.append(ent)

    return unique_entities[:50]  # Limit results


def _load_spacy_model() -> object | None:
    """Load spaCy model with thread safety and fallback support.

    Tries models in order from settings until one loads successfully.
    Returns None if no model can be loaded.
    """
    global _NLP, _NLP_AVAILABLE

    if not SPACY_AVAILABLE:
        return None

    with _NLP_LOCK:
        if _NLP is not None:
            return _NLP

        if not _NLP_AVAILABLE:
            return None

        # Try each model in preference order
        for model_name in settings.nlp.spacy_models:
            try:
                _NLP = spacy.load(model_name)
                return _NLP
            except OSError:
                continue

        # No model loaded - mark as unavailable to avoid repeated attempts
        _NLP_AVAILABLE = False
        return None


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len([word for word in text.split() if word])


def _is_definition_paragraph(text: str) -> bool:
    """
    Detect definition patterns in multiple languages.
    Returns True if the paragraph contains definition-like structures.
    """
    if not text:
        return False

    # Chinese patterns
    chinese_keywords = ("是", "指的是", "可以理解為", "為", "意指", "定義為", "係指")
    if any(keyword in text for keyword in chinese_keywords):
        return True
    if " 是 " in text or " 為 " in text:
        return True

    # English patterns
    english_patterns = [
        r"\bis\s+defined\s+as\b",
        r"\brefers\s+to\b",
        r"\bmeans\s+that\b",
        r"\bis\s+known\s+as\b",
        r"\bis\s+a\s+type\s+of\b",
        r"\bis\s+characterized\s+by\b",
        r"\bcan\s+be\s+described\s+as\b",
        r"\bis\s+the\s+process\s+of\b",
        r"\bis\s+when\b",
        r":\s*[A-Z]",  # Colon followed by capital letter (definition style)
    ]
    for pattern in english_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    # Japanese patterns
    japanese_patterns = ["とは", "である", "を意味する", "と定義される", "のことを指す"]
    if any(pattern in text for pattern in japanese_patterns):
        return True

    # Korean patterns
    korean_patterns = ["이란", "란", "를 의미", "을 뜻", "라고 정의"]
    if any(pattern in text for pattern in korean_patterns):
        return True

    return False


def _detect_quotable_sentences(text: str) -> list[dict]:
    """
    Detect sentences that are highly quotable by AI.
    Returns list of quotable sentences with their type.
    """
    quotable = []

    # Split into sentences
    sentences = re.split(r'[.。!?！？]+', text)

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20:
            continue

        quote_type = None

        # Check for statistics/numbers
        if re.search(r'\d+%|\d+\s*percent|統計|調查|研究顯示|according to', sentence, re.IGNORECASE):
            quote_type = "statistic"

        # Check for definitions
        elif _is_definition_paragraph(sentence):
            quote_type = "definition"

        # Check for facts with specific numbers
        elif re.search(r'\b(19|20)\d{2}\b|\b\d{1,3}(,\d{3})+\b', sentence):
            quote_type = "fact"

        # Check for expert citations
        elif re.search(r'according to|研究指出|專家表示|reported by', sentence, re.IGNORECASE):
            quote_type = "citation"

        if quote_type:
            quotable.append({
                "text": sentence[:200],  # Limit length
                "type": quote_type
            })

    return quotable[:5]  # Return top 5 quotable sentences


def _calculate_readability(text: str) -> dict:
    """
    Calculate readability metrics using textstat.
    Returns dict with various readability scores.
    """
    if not TEXTSTAT_AVAILABLE or not text or len(text) < 100:
        return {
            "available": False,
            "flesch_reading_ease": None,
            "flesch_kincaid_grade": None,
            "gunning_fog": None,
            "smog_index": None,
            "automated_readability_index": None,
            "coleman_liau_index": None,
            "avg_sentence_length": None,
            "avg_syllables_per_word": None,
            "difficult_words_percent": None,
            "reading_level": None,
            "reading_time_minutes": None,
        }

    try:
        # Calculate metrics
        flesch = textstat.flesch_reading_ease(text)
        fk_grade = textstat.flesch_kincaid_grade(text)
        gunning = textstat.gunning_fog(text)
        smog = textstat.smog_index(text)
        ari = textstat.automated_readability_index(text)
        coleman = textstat.coleman_liau_index(text)
        avg_sentence = textstat.avg_sentence_length(text)
        avg_syllables = textstat.avg_syllables_per_word(text)
        difficult_words = textstat.difficult_words(text)
        word_count = textstat.lexicon_count(text, removepunct=True)

        # Calculate difficult words percentage
        difficult_percent = (difficult_words / word_count * 100) if word_count > 0 else 0

        # Determine reading level based on Flesch score
        if flesch >= 90:
            reading_level = "very_easy"
        elif flesch >= 80:
            reading_level = "easy"
        elif flesch >= 70:
            reading_level = "fairly_easy"
        elif flesch >= 60:
            reading_level = "standard"
        elif flesch >= 50:
            reading_level = "fairly_difficult"
        elif flesch >= 30:
            reading_level = "difficult"
        else:
            reading_level = "very_difficult"

        # Calculate reading time (assuming 200 words per minute)
        reading_time_minutes = word_count / 200 if word_count > 0 else 0

        return {
            "available": True,
            "flesch_reading_ease": round(flesch, 1),
            "flesch_kincaid_grade": round(fk_grade, 1),
            "gunning_fog": round(gunning, 1),
            "smog_index": round(smog, 1),
            "automated_readability_index": round(ari, 1),
            "coleman_liau_index": round(coleman, 1),
            "avg_sentence_length": round(avg_sentence, 1),
            "avg_syllables_per_word": round(avg_syllables, 2),
            "difficult_words_percent": round(difficult_percent, 1),
            "reading_level": reading_level,
            "reading_time_minutes": round(reading_time_minutes, 1),
        }
    except Exception:
        return {
            "available": False,
            "flesch_reading_ease": None,
            "flesch_kincaid_grade": None,
            "gunning_fog": None,
            "smog_index": None,
            "automated_readability_index": None,
            "coleman_liau_index": None,
            "avg_sentence_length": None,
            "avg_syllables_per_word": None,
            "difficult_words_percent": None,
            "reading_level": None,
            "reading_time_minutes": None,
        }


def _extract_schema_org(html: str, url: str = "") -> dict:
    """
    Extract Schema.org structured data from HTML.
    Returns dict with found schemas and their types.
    """
    if not EXTRUCT_AVAILABLE:
        return {
            "available": False,
            "schemas": [],
            "types_found": [],
            "has_article": False,
            "has_faq": False,
            "has_howto": False,
            "has_qa": False,
            "has_organization": False,
            "has_person": False,
            "has_product": False,
            "has_breadcrumb": False,
            "score_contribution": 0,
        }

    try:
        data = extruct.extract(
            html,
            base_url=url,
            syntaxes=['json-ld', 'microdata', 'rdfa'],
            uniform=True
        )

        schemas = []
        types_found = set()

        # Process JSON-LD
        for item in data.get('json-ld', []):
            if isinstance(item, dict):
                schema_type = item.get('@type', 'Unknown')
                if isinstance(schema_type, list):
                    schema_type = schema_type[0] if schema_type else 'Unknown'
                types_found.add(schema_type)
                schemas.append({
                    "type": schema_type,
                    "source": "json-ld",
                    "data": item
                })

        # Process microdata
        for item in data.get('microdata', []):
            if isinstance(item, dict):
                schema_type = item.get('@type', 'Unknown')
                types_found.add(schema_type)
                schemas.append({
                    "type": schema_type,
                    "source": "microdata",
                    "data": item
                })

        # Process RDFa
        for item in data.get('rdfa', []):
            if isinstance(item, dict):
                schema_type = item.get('@type', 'Unknown')
                types_found.add(schema_type)
                schemas.append({
                    "type": schema_type,
                    "source": "rdfa",
                    "data": item
                })

        types_list = list(types_found)

        # Check for specific important schema types
        has_article = any(t in types_found for t in ['Article', 'NewsArticle', 'BlogPosting', 'TechArticle'])
        has_faq = 'FAQPage' in types_found
        has_howto = 'HowTo' in types_found
        has_qa = any(t in types_found for t in ['QAPage', 'Question', 'Answer'])
        has_organization = 'Organization' in types_found
        has_person = 'Person' in types_found
        has_product = any(t in types_found for t in ['Product', 'Offer'])
        has_breadcrumb = 'BreadcrumbList' in types_found

        # Calculate score contribution (0-15 points possible)
        score = 0
        if schemas:
            score += 5  # Base points for having any schema
        if has_article:
            score += 3
        if has_faq:
            score += 4  # FAQ is very valuable for AI
        if has_howto:
            score += 3
        if has_qa:
            score += 3
        if has_breadcrumb:
            score += 1
        score = min(score, 15)  # Cap at 15

        return {
            "available": True,
            "schemas": schemas[:10],  # Limit to 10 schemas
            "types_found": types_list,
            "has_article": has_article,
            "has_faq": has_faq,
            "has_howto": has_howto,
            "has_qa": has_qa,
            "has_organization": has_organization,
            "has_person": has_person,
            "has_product": has_product,
            "has_breadcrumb": has_breadcrumb,
            "score_contribution": score,
        }

    except Exception:
        return {
            "available": False,
            "schemas": [],
            "types_found": [],
            "has_article": False,
            "has_faq": False,
            "has_howto": False,
            "has_qa": False,
            "has_organization": False,
            "has_person": False,
            "has_product": False,
            "has_breadcrumb": False,
            "score_contribution": 0,
        }


def _content_surface_components(headings_count: int, paragraphs: list[str], lists: list[list[str]], tables: list[list[str]]) -> dict:
    paragraph_blocks = sum(1 for text in paragraphs if len(text) >= 10)
    definition_blocks = sum(1 for text in paragraphs if _is_definition_paragraph(text))
    components = {
        "heading_blocks": headings_count,
        "paragraph_blocks": paragraph_blocks,
        "list_blocks": len(lists),
        "table_blocks": len(tables),
        "definition_blocks": definition_blocks,
    }
    components["score"] = sum(components.values())
    return components


def _in_ancestor(tag, names: Iterable[str]) -> bool:
    return tag.find_parent(list(names)) is not None


def _classify_link(href: str, base_url: str) -> str:
    if not href:
        return "external"
    parsed = urlparse(href)
    if parsed.scheme in {"http", "https"}:
        if base_url:
            base_netloc = urlparse(base_url).netloc
            return "internal" if parsed.netloc == base_netloc else "external"
        return "external"
    return "internal" if base_url or not parsed.scheme else "external"


def _calculate_content_ratio(html: str, main_content: str) -> float:
    """Calculate ratio of main content to total page content."""
    try:
        soup = BeautifulSoup(html, "lxml")
        # Remove script, style, nav, footer, header
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        total_text = _clean_text(soup.get_text())
        main_text = _clean_text(main_content)

        if not total_text:
            return 0.0

        ratio = len(main_text) / len(total_text) if len(total_text) > 0 else 0
        return round(min(ratio, 1.0), 2)
    except Exception:
        return 0.0


def parse_content(html: str, url: str = "") -> dict:
    """Parse main content from HTML into a structured JSON-like dict."""
    soup = BeautifulSoup(html, "lxml")
    title = _clean_text(soup.title.text) if soup.title and soup.title.text else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = _clean_text(description_tag["content"]) if description_tag and description_tag.get("content") else ""
    canonical_tag = soup.find("link", attrs={"rel": lambda val: val and "canonical" in val})
    canonical = canonical_tag.get("href", "") if canonical_tag else ""

    main_html = Document(html).summary(html_partial=True)
    main_soup = BeautifulSoup(main_html, "lxml")
    content_root = main_soup.body or main_soup

    headings = []
    paragraphs = []
    lists = []
    tables = []
    blocks = []
    current_heading = None

    for element in content_root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table"]):
        if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if _in_ancestor(element, ["ul", "ol", "table"]):
                continue
            text = _clean_text(element.get_text(" ", strip=True))
            if not text:
                continue
            current_heading = {"level": element.name, "text": text, "paragraphs": []}
            headings.append(current_heading)
            blocks.append({"type": "heading", "level": element.name, "text": text})
            continue

        if element.name == "p":
            if _in_ancestor(element, ["ul", "ol", "table"]):
                continue
            text = _clean_text(element.get_text(" ", strip=True))
            if not text:
                continue
            paragraphs.append(text)
            blocks.append({"type": "paragraph", "text": text})
            if current_heading is not None:
                current_heading["paragraphs"].append(text)
            continue

        if element.name in {"ul", "ol"}:
            if _in_ancestor(element, ["ul", "ol", "table"]):
                continue
            items = []
            for li in element.find_all("li", recursive=False):
                item_text = _clean_text(li.get_text(" ", strip=True))
                if item_text:
                    items.append(item_text)
            if items:
                lists.append(items)
                blocks.append({"type": "list", "items": items})
            continue

        if element.name == "table":
            if _in_ancestor(element, ["table"]):
                continue
            rows = []
            for row in element.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                row_text = _clean_text(" | ".join(cell for cell in cells if cell))
                if row_text:
                    rows.append(row_text)
            if rows:
                tables.append(rows)
                blocks.append({"type": "table", "rows": rows})

    base_url = url if urlparse(url).scheme in {"http", "https"} else ""
    internal_links = []
    external_links = []
    for link in content_root.find_all("a", href=True):
        href = link.get("href", "")
        resolved = urljoin(base_url, href) if base_url else href
        text = _clean_text(link.get_text(" ", strip=True))
        link_info = {"href": resolved, "text": text}
        if _classify_link(resolved, base_url) == "internal":
            internal_links.append(link_info)
        else:
            external_links.append(link_info)

    # Entity extraction with multilingual support
    entities = []
    all_paragraph_text = " ".join(paragraphs)
    detected_lang = _detect_language(all_paragraph_text)

    nlp = _load_spacy_model()
    use_cjk_fallback = (
        settings.nlp.enable_cjk_fallback
        and detected_lang in ("zh", "ja", "ko")
    )

    if nlp is not None and not use_cjk_fallback:
        # Use spaCy for entity extraction
        for index, paragraph in enumerate(paragraphs):
            try:
                doc = nlp(paragraph)
                for ent in doc.ents:
                    if ent.label_ in settings.nlp.entity_labels:
                        entities.append({
                            "text": ent.text,
                            "label": ent.label_,
                            "paragraph_index": index,
                            "source": "spacy"
                        })
            except Exception:
                # Skip paragraphs that fail to process
                continue

    # For CJK content or when spaCy is unavailable, use pattern matching
    if use_cjk_fallback or (nlp is None and settings.nlp.enable_cjk_fallback):
        cjk_entities = _extract_cjk_entities(all_paragraph_text)
        # Add paragraph_index (approximate based on where entity appears)
        for ent in cjk_entities:
            for idx, para in enumerate(paragraphs):
                if ent["text"] in para:
                    ent["paragraph_index"] = idx
                    break
            else:
                ent["paragraph_index"] = 0
        entities.extend(cjk_entities)

    # Deduplicate entities
    seen = set()
    unique_entities = []
    for ent in entities:
        key = (ent["text"], ent["label"])
        if key not in seen:
            seen.add(key)
            unique_entities.append(ent)
    entities = unique_entities[:100]  # Limit to 100 entities

    block_texts = []
    block_texts.extend(paragraphs)
    for items in lists:
        block_texts.extend(items)
    for rows in tables:
        block_texts.extend(rows)
    word_count = sum(_word_count(text) for text in block_texts)
    paragraph_count = len(paragraphs)
    surface_components = _content_surface_components(len(headings), paragraphs, lists, tables)
    avg_paragraph_length = (
        int(word_count / paragraph_count) if paragraph_count else 0
    )

    # Calculate new metrics
    all_text = " ".join(paragraphs)
    readability = _calculate_readability(all_text)
    schema_org = _extract_schema_org(html, url)
    quotable_sentences = _detect_quotable_sentences(all_text)
    content_ratio = _calculate_content_ratio(html, all_text)

    return {
        "url": url,
        "meta": {
            "title": title,
            "description": description,
            "canonical": canonical,
        },
        "content": {
            "headings": headings,
            "paragraphs": paragraphs,
            "lists": lists,
            "tables": tables,
            "blocks": blocks,
        },
        "links": {
            "internal": internal_links,
            "external": external_links,
        },
        "entities": entities,
        "stats": {
            "word_count": word_count,
            "paragraph_count": paragraph_count,
            "avg_paragraph_length": avg_paragraph_length,
            "heading_count": len(headings),
            "internal_links": len(internal_links),
            "external_links": len(external_links),
            "content_ratio": content_ratio,
        },
        "content_surface_size": {
            "score": surface_components["score"],
            "components": {
                "heading_blocks": surface_components["heading_blocks"],
                "paragraph_blocks": surface_components["paragraph_blocks"],
                "list_blocks": surface_components["list_blocks"],
                "table_blocks": surface_components["table_blocks"],
                "definition_blocks": surface_components["definition_blocks"],
            },
        },
        "readability": readability,
        "schema_org": schema_org,
        "quotable_sentences": quotable_sentences,
    }
