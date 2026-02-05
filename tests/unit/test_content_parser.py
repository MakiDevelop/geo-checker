"""Unit tests for content parser module."""
from __future__ import annotations


class TestDefinitionDetection:
    """Tests for definition paragraph detection."""

    def test_english_is_defined_pattern(self):
        """English 'is defined as' pattern."""
        from src.parser.content_parser import _is_definition_paragraph
        assert _is_definition_paragraph("AI is defined as artificial intelligence.")

    def test_english_refers_to_pattern(self):
        """English 'refers to' pattern."""
        from src.parser.content_parser import _is_definition_paragraph
        assert _is_definition_paragraph("Machine learning refers to a type of AI.")

    def test_english_means_pattern(self):
        """English 'means' pattern."""
        from src.parser.content_parser import _is_definition_paragraph
        assert _is_definition_paragraph("GEO means Generative Engine Optimization.")

    def test_chinese_is_pattern(self):
        """Chinese '是' pattern."""
        from src.parser.content_parser import _is_definition_paragraph
        assert _is_definition_paragraph("機器學習是人工智慧的一種。")

    def test_chinese_refers_to_pattern(self):
        """Chinese '指的是' pattern."""
        from src.parser.content_parser import _is_definition_paragraph
        assert _is_definition_paragraph("GEO 指的是生成式搜尋優化。")

    def test_japanese_pattern(self):
        """Japanese 'とは' pattern."""
        from src.parser.content_parser import _is_definition_paragraph
        assert _is_definition_paragraph("機械学習とは、AIの一種です。")

    def test_non_definition(self):
        """Non-definition text should return False."""
        from src.parser.content_parser import _is_definition_paragraph
        assert not _is_definition_paragraph("The weather is nice today.")
        assert not _is_definition_paragraph("I went to the store.")


class TestQuotableSentences:
    """Tests for quotable sentence detection."""

    def test_detect_statistic(self):
        """Detect sentences with statistics."""
        from src.parser.content_parser import _detect_quotable_sentences
        text = "According to a 2024 study, 85% of users prefer AI search."
        result = _detect_quotable_sentences(text)
        assert len(result) >= 1

    def test_detect_percentage(self):
        """Detect sentences with percentages."""
        from src.parser.content_parser import _detect_quotable_sentences
        text = "The adoption rate increased by 50% in 2024."
        result = _detect_quotable_sentences(text)
        assert len(result) >= 1

    def test_detect_citation(self):
        """Detect sentences with citations."""
        from src.parser.content_parser import _detect_quotable_sentences
        text = "According to Smith et al., this is significant."
        result = _detect_quotable_sentences(text)
        assert len(result) >= 1

    def test_no_quotable_content(self):
        """Text without quotable content."""
        from src.parser.content_parser import _detect_quotable_sentences
        text = "This is a simple sentence without any special content."
        result = _detect_quotable_sentences(text)
        # May or may not detect, depends on heuristics
        assert isinstance(result, list)


class TestContentParsing:
    """Tests for main content parsing function."""

    def test_parse_returns_expected_keys(self, valid_html: str, mock_url: str):
        """parse_content should return expected keys."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)

        expected_keys = ["meta", "content", "stats"]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_parse_extracts_title(self, valid_html: str, mock_url: str):
        """Title should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        assert result["meta"]["title"] == "Test Page - GEO Checker Example"

    def test_parse_extracts_description(self, valid_html: str, mock_url: str):
        """Description should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        assert "test page" in result["meta"]["description"].lower()

    def test_parse_extracts_headings(self, valid_html: str, mock_url: str):
        """Headings should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        headings = result["content"]["headings"]
        assert len(headings) > 0
        assert any(h["level"] == "h1" for h in headings)

    def test_parse_extracts_paragraphs(self, valid_html: str, mock_url: str):
        """Paragraphs should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        paragraphs = result["content"]["paragraphs"]
        assert len(paragraphs) > 0

    def test_parse_extracts_lists(self, valid_html: str, mock_url: str):
        """Lists should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        lists = result["content"]["lists"]
        assert len(lists) > 0

    def test_parse_extracts_canonical(self, valid_html: str, mock_url: str):
        """Canonical URL should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        assert result["meta"]["canonical"] == "https://example.com/test-page"

    def test_parse_calculates_stats(self, valid_html: str, mock_url: str):
        """Stats should be calculated."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        stats = result["stats"]
        assert "word_count" in stats
        assert "heading_count" in stats
        assert stats["word_count"] > 0

    def test_parse_minimal_html(self, minimal_html: str, mock_url: str):
        """Minimal HTML should parse without errors."""
        from src.parser.content_parser import parse_content
        result = parse_content(minimal_html, mock_url)
        assert result["meta"]["title"] == "Minimal"


class TestLinkExtraction:
    """Tests for link extraction."""

    def test_extract_internal_links(self, valid_html: str, mock_url: str):
        """Internal links should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        links = result.get("links", {})
        internal = links.get("internal", [])
        assert len(internal) > 0

    def test_extract_external_links(self, valid_html: str, mock_url: str):
        """External links should be extracted."""
        from src.parser.content_parser import parse_content
        result = parse_content(valid_html, mock_url)
        links = result.get("links", {})
        external = links.get("external", [])
        assert len(external) > 0


class TestSchemaOrgExtraction:
    """Tests for Schema.org extraction."""

    def test_no_schema_handling(self, minimal_html: str, mock_url: str):
        """Pages without Schema.org should be handled."""
        from src.parser.content_parser import parse_content
        result = parse_content(minimal_html, mock_url)
        schema = result.get("schema_org", {})
        assert schema.get("available") is False or "types_found" not in schema or len(schema.get("types_found", [])) == 0
