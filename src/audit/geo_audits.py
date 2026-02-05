"""GEO-specific audit implementations."""
from __future__ import annotations

from typing import Any

from src.audit.base import AuditResult, AuditSeverity, BaseAudit
from src.config.settings import settings


class CrawlerAccessAudit(BaseAudit):
    """Audit for AI crawler accessibility."""

    @property
    def audit_id(self) -> str:
        return "geo.crawler_access"

    @property
    def name(self) -> str:
        return "AI Crawler Access"

    @property
    def description(self) -> str:
        return "Checks if major AI crawlers (GPTBot, ClaudeBot, etc.) can access the page"

    @property
    def category(self) -> str:
        return "accessibility"

    @property
    def weight(self) -> float:
        return 2.0  # Important audit

    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Check AI crawler access from context."""
        ai_access = context.get("ai_access", {})

        crawlers = {
            "GPTBot": ai_access.get("gptbot", "unspecified"),
            "ClaudeBot": ai_access.get("claudebot", "unspecified"),
            "PerplexityBot": ai_access.get("perplexitybot", "unspecified"),
            "Google-Extended": ai_access.get("google_extended", "unspecified"),
        }

        blocked = [name for name, status in crawlers.items() if status == "disallow"]
        allowed = [name for name, status in crawlers.items() if status == "allow"]

        # Calculate score (25 points per allowed crawler)
        score = len(allowed) * 25
        max_score = 100

        if blocked:
            severity = AuditSeverity.CRITICAL
            passed = False
            message = f"{len(blocked)} AI crawler(s) blocked: {', '.join(blocked)}"
            recommendation = "Update robots.txt to allow AI crawlers for better visibility"
        elif not allowed:
            severity = AuditSeverity.WARNING
            passed = True
            message = "No explicit AI crawler rules found (default: allowed)"
            recommendation = "Consider explicitly allowing AI crawlers in robots.txt"
        else:
            severity = AuditSeverity.PASS
            passed = True
            message = f"All {len(allowed)} AI crawlers have access"
            recommendation = None

        return AuditResult(
            audit_id=self.audit_id,
            name=self.name,
            severity=severity,
            score=score,
            max_score=max_score,
            passed=passed,
            message=message,
            details={
                "crawlers": crawlers,
                "blocked": blocked,
                "allowed": allowed,
            },
            recommendation=recommendation,
        )


class MetaRobotsAudit(BaseAudit):
    """Audit for meta robots directives."""

    @property
    def audit_id(self) -> str:
        return "geo.meta_robots"

    @property
    def name(self) -> str:
        return "Meta Robots Directives"

    @property
    def description(self) -> str:
        return "Checks for noindex/nofollow directives that block AI indexing"

    @property
    def category(self) -> str:
        return "accessibility"

    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Check meta robots and X-Robots-Tag."""
        ai_access = context.get("ai_access", {})
        meta_robots = ai_access.get("meta_robots", {})
        x_robots = ai_access.get("x_robots_tag", {})

        noindex = meta_robots.get("noindex", False) or x_robots.get("noindex", False)
        nofollow = meta_robots.get("nofollow", False) or x_robots.get("nofollow", False)

        score = 100
        issues = []

        if noindex:
            score -= settings.geo_scoring.noindex_penalty * 2.5  # Scale to 100
            issues.append("noindex")
        if nofollow:
            score -= settings.geo_scoring.nofollow_penalty * 2
            issues.append("nofollow")

        score = max(0, score)

        if noindex:
            severity = AuditSeverity.CRITICAL
            passed = False
            message = "Page has noindex directive - AI cannot index this content"
            recommendation = "Remove noindex if you want AI systems to reference this page"
        elif nofollow:
            severity = AuditSeverity.WARNING
            passed = True
            message = "Page has nofollow directive - links won't be followed"
            recommendation = "Remove nofollow if you want AI to discover linked content"
        else:
            severity = AuditSeverity.PASS
            passed = True
            message = "No blocking directives found"
            recommendation = None

        return AuditResult(
            audit_id=self.audit_id,
            name=self.name,
            severity=severity,
            score=score,
            max_score=100,
            passed=passed,
            message=message,
            details={
                "meta_robots": meta_robots,
                "x_robots_tag": x_robots,
                "issues": issues,
            },
            recommendation=recommendation,
        )


class HeadingStructureAudit(BaseAudit):
    """Audit for heading structure quality."""

    @property
    def audit_id(self) -> str:
        return "geo.headings"

    @property
    def name(self) -> str:
        return "Heading Structure"

    @property
    def description(self) -> str:
        return "Evaluates heading hierarchy for AI content understanding"

    @property
    def category(self) -> str:
        return "structure"

    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Evaluate heading structure."""
        headings = parsed.get("content", {}).get("headings", [])
        heading_count = len(headings)

        cfg = settings.geo_scoring
        if heading_count >= cfg.heading_excellent_threshold:
            score = 100
            severity = AuditSeverity.PASS
            message = f"Excellent heading structure ({heading_count} headings)"
        elif heading_count >= cfg.heading_good_threshold:
            score = 75
            severity = AuditSeverity.PASS
            message = f"Good heading structure ({heading_count} headings)"
        elif heading_count >= 1:
            score = 50
            severity = AuditSeverity.INFO
            message = f"Minimal heading structure ({heading_count} heading(s))"
        else:
            score = 0
            severity = AuditSeverity.WARNING
            message = "No headings found"

        # Check for H1
        h1_count = sum(1 for h in headings if h.get("level") == "h1")
        if h1_count == 0:
            score = max(0, score - 25)
            recommendation = "Add an H1 heading to establish page topic"
        elif h1_count > 1:
            score = max(0, score - 10)
            recommendation = "Use only one H1 per page"
        else:
            recommendation = None if score >= 75 else "Add more subheadings (H2, H3) to organize content"

        return AuditResult(
            audit_id=self.audit_id,
            name=self.name,
            severity=severity,
            score=score,
            max_score=100,
            passed=score >= 50,
            message=message,
            details={
                "heading_count": heading_count,
                "h1_count": h1_count,
                "levels": [h.get("level") for h in headings],
            },
            recommendation=recommendation,
        )


class SchemaOrgAudit(BaseAudit):
    """Audit for Schema.org structured data."""

    @property
    def audit_id(self) -> str:
        return "geo.schema_org"

    @property
    def name(self) -> str:
        return "Schema.org Structured Data"

    @property
    def description(self) -> str:
        return "Checks for Schema.org markup that helps AI understand content"

    @property
    def category(self) -> str:
        return "structure"

    @property
    def weight(self) -> float:
        return 1.5  # Moderately important

    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Evaluate Schema.org presence and quality."""
        schema = parsed.get("schema_org", {})

        if not schema.get("available"):
            return AuditResult(
                audit_id=self.audit_id,
                name=self.name,
                severity=AuditSeverity.WARNING,
                score=0,
                max_score=100,
                passed=False,
                message="No Schema.org structured data found",
                details={},
                recommendation="Add Schema.org markup (Article, FAQPage, HowTo) for better AI understanding",
            )

        types_found = schema.get("types_found", [])
        score_contribution = schema.get("score_contribution", 0)

        # Scale to 100
        score = min(100, score_contribution * 6.67)

        # Check for AI-valuable schemas
        valuable_schemas = []
        if schema.get("has_faq"):
            valuable_schemas.append("FAQPage")
        if schema.get("has_article"):
            valuable_schemas.append("Article")
        if schema.get("has_howto"):
            valuable_schemas.append("HowTo")

        if valuable_schemas:
            severity = AuditSeverity.PASS
            message = f"Found AI-valuable schemas: {', '.join(valuable_schemas)}"
            recommendation = None
        elif types_found:
            severity = AuditSeverity.INFO
            message = f"Found schemas: {', '.join(types_found[:3])}"
            recommendation = "Consider adding FAQPage or Article schema for better AI visibility"
        else:
            severity = AuditSeverity.WARNING
            message = "Schema.org data present but no types identified"
            recommendation = "Verify Schema.org implementation is correct"

        return AuditResult(
            audit_id=self.audit_id,
            name=self.name,
            severity=severity,
            score=score,
            max_score=100,
            passed=score >= 50,
            message=message,
            details={
                "types_found": types_found,
                "has_faq": schema.get("has_faq", False),
                "has_article": schema.get("has_article", False),
                "has_howto": schema.get("has_howto", False),
            },
            recommendation=recommendation,
        )


class ContentQualityAudit(BaseAudit):
    """Audit for content quality indicators."""

    @property
    def audit_id(self) -> str:
        return "geo.content_quality"

    @property
    def name(self) -> str:
        return "Content Quality"

    @property
    def description(self) -> str:
        return "Evaluates readability, definitions, and quotable content"

    @property
    def category(self) -> str:
        return "quality"

    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Evaluate content quality metrics."""
        readability = parsed.get("readability", {})
        components = parsed.get("content_surface_size", {}).get("components", {})
        quotable = parsed.get("quotable_sentences", [])
        stats = parsed.get("stats", {})

        score = 0
        max_score = 100
        issues = []
        positives = []

        # Readability (30 points)
        if readability.get("available"):
            flesch = readability.get("flesch_reading_ease", 50)
            cfg = settings.geo_scoring

            if flesch >= cfg.flesch_excellent_threshold:
                score += 30
                positives.append("Excellent readability")
            elif flesch >= cfg.flesch_good_threshold:
                score += 25
                positives.append("Good readability")
            elif flesch >= cfg.flesch_fair_threshold:
                score += 20
            elif flesch >= cfg.flesch_poor_threshold:
                score += 15
                issues.append("Low readability")
            else:
                score += 10
                issues.append("Very low readability")
        else:
            score += 15  # Default when not available

        # Definition density (30 points)
        definition_blocks = components.get("definition_blocks", 0)
        cfg = settings.geo_scoring

        if definition_blocks >= cfg.definition_excellent_threshold:
            score += 30
            positives.append(f"{definition_blocks} definition paragraphs")
        elif definition_blocks >= cfg.definition_good_threshold:
            score += 25
        elif definition_blocks >= 1:
            score += 15
        else:
            issues.append("No definition-style content")

        # Content ratio (20 points)
        content_ratio = stats.get("content_ratio", 0.5)
        cfg = settings.geo_scoring

        if content_ratio >= cfg.content_ratio_excellent_threshold:
            score += 20
            positives.append("High content ratio")
        elif content_ratio >= cfg.content_ratio_good_threshold:
            score += 15
        elif content_ratio >= 0.3:
            score += 10
        else:
            issues.append("Low content ratio (too much boilerplate)")

        # Quotable content (20 points)
        quotable_count = len(quotable)
        if quotable_count >= cfg.quotable_excellent_threshold:
            score += 20
            positives.append(f"{quotable_count} quotable sentences")
        elif quotable_count >= 1:
            score += 12
        else:
            issues.append("No highly quotable content")

        # Determine severity
        if score >= 75:
            severity = AuditSeverity.PASS
            message = f"Good content quality ({', '.join(positives[:2])})"
        elif score >= 50:
            severity = AuditSeverity.INFO
            message = "Fair content quality"
        else:
            severity = AuditSeverity.WARNING
            message = "Content quality needs improvement"

        # Build recommendation
        if issues:
            recommendation = f"Consider: {'; '.join(issues[:2])}"
        else:
            recommendation = None

        return AuditResult(
            audit_id=self.audit_id,
            name=self.name,
            severity=severity,
            score=score,
            max_score=max_score,
            passed=score >= 50,
            message=message,
            details={
                "flesch_reading_ease": readability.get("flesch_reading_ease"),
                "definition_blocks": definition_blocks,
                "content_ratio": content_ratio,
                "quotable_count": quotable_count,
                "issues": issues,
                "positives": positives,
            },
            recommendation=recommendation,
        )


# Register all GEO audits
def register_geo_audits(registry):
    """Register all GEO audits with the given registry."""
    registry.register(CrawlerAccessAudit())
    registry.register(MetaRobotsAudit())
    registry.register(HeadingStructureAudit())
    registry.register(SchemaOrgAudit())
    registry.register(ContentQualityAudit())
