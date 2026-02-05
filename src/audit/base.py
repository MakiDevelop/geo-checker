"""Base classes for audit framework."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AuditSeverity(Enum):
    """Severity levels for audit findings."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    PASS = "pass"


@dataclass
class AuditResult:
    """Result of a single audit check.

    Attributes:
        audit_id: Unique identifier for this audit type
        name: Human-readable name of the audit
        severity: Severity level of the finding
        score: Numeric score (0-100 or audit-specific range)
        max_score: Maximum possible score for this audit
        passed: Whether the audit passed
        message: Human-readable description of the finding
        details: Additional details or data
        recommendation: Suggested fix or improvement
    """
    audit_id: str
    name: str
    severity: AuditSeverity
    score: float
    max_score: float
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    recommendation: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "audit_id": self.audit_id,
            "name": self.name,
            "severity": self.severity.value,
            "score": self.score,
            "max_score": self.max_score,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
            "recommendation": self.recommendation,
        }


class BaseAudit(ABC):
    """Abstract base class for all audit checks.

    Subclasses must implement:
    - audit_id: Unique identifier
    - name: Human-readable name
    - run(): Execute the audit and return AuditResult
    """

    @property
    @abstractmethod
    def audit_id(self) -> str:
        """Unique identifier for this audit type."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this audit."""
        pass

    @property
    def description(self) -> str:
        """Optional description of what this audit checks."""
        return ""

    @property
    def category(self) -> str:
        """Category for grouping audits (e.g., 'accessibility', 'structure', 'quality')."""
        return "general"

    @property
    def weight(self) -> float:
        """Weight for scoring (default 1.0)."""
        return 1.0

    @abstractmethod
    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Execute the audit check.

        Args:
            parsed: Parsed content dictionary from content_parser
            html: Raw HTML string
            url: URL of the page being analyzed
            **context: Additional context (e.g., robots.txt data, headers)

        Returns:
            AuditResult with findings
        """
        pass


class CompositeAudit(BaseAudit):
    """An audit that runs multiple sub-audits and aggregates results.

    Useful for grouping related checks together.
    """

    def __init__(self, sub_audits: list[BaseAudit]):
        self._sub_audits = sub_audits

    @property
    def audit_id(self) -> str:
        return "composite"

    @property
    def name(self) -> str:
        return "Composite Audit"

    def run(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context: Any
    ) -> AuditResult:
        """Run all sub-audits and aggregate results."""
        results = []
        total_score = 0
        total_max = 0

        for audit in self._sub_audits:
            result = audit.run(parsed, html, url, **context)
            results.append(result)
            total_score += result.score * audit.weight
            total_max += result.max_score * audit.weight

        # Determine overall severity (worst case)
        severities = [r.severity for r in results]
        if AuditSeverity.CRITICAL in severities:
            overall_severity = AuditSeverity.CRITICAL
        elif AuditSeverity.WARNING in severities:
            overall_severity = AuditSeverity.WARNING
        elif AuditSeverity.INFO in severities:
            overall_severity = AuditSeverity.INFO
        else:
            overall_severity = AuditSeverity.PASS

        all_passed = all(r.passed for r in results)

        return AuditResult(
            audit_id=self.audit_id,
            name=self.name,
            severity=overall_severity,
            score=total_score,
            max_score=total_max,
            passed=all_passed,
            message=f"Ran {len(results)} sub-audits",
            details={
                "sub_results": [r.to_dict() for r in results],
            },
        )
