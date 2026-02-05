"""Audit registry for managing available audits."""
from __future__ import annotations

from src.audit.base import AuditResult, BaseAudit


class AuditRegistry:
    """Registry for managing and running audit checks.

    Usage:
        registry = AuditRegistry()
        registry.register(MyAudit())
        results = registry.run_all(parsed, html, url)
    """

    def __init__(self):
        self._audits: dict[str, BaseAudit] = {}
        self._categories: dict[str, list[str]] = {}

    def register(self, audit: BaseAudit) -> None:
        """Register an audit instance.

        Args:
            audit: Audit instance to register
        """
        self._audits[audit.audit_id] = audit

        # Track by category
        category = audit.category
        if category not in self._categories:
            self._categories[category] = []
        self._categories[category].append(audit.audit_id)

    def unregister(self, audit_id: str) -> None:
        """Unregister an audit by ID.

        Args:
            audit_id: ID of audit to remove
        """
        if audit_id in self._audits:
            audit = self._audits[audit_id]
            del self._audits[audit_id]

            # Remove from category tracking
            category = audit.category
            if category in self._categories:
                self._categories[category] = [
                    aid for aid in self._categories[category]
                    if aid != audit_id
                ]

    def get(self, audit_id: str) -> BaseAudit | None:
        """Get an audit by ID.

        Args:
            audit_id: ID of audit to retrieve

        Returns:
            Audit instance or None if not found
        """
        return self._audits.get(audit_id)

    def get_by_category(self, category: str) -> list[BaseAudit]:
        """Get all audits in a category.

        Args:
            category: Category name

        Returns:
            List of audit instances in the category
        """
        audit_ids = self._categories.get(category, [])
        return [self._audits[aid] for aid in audit_ids if aid in self._audits]

    def list_all(self) -> list[BaseAudit]:
        """List all registered audits.

        Returns:
            List of all audit instances
        """
        return list(self._audits.values())

    def list_categories(self) -> list[str]:
        """List all categories.

        Returns:
            List of category names
        """
        return list(self._categories.keys())

    def run(
        self,
        audit_id: str,
        parsed: dict,
        html: str,
        url: str,
        **context
    ) -> AuditResult | None:
        """Run a specific audit.

        Args:
            audit_id: ID of audit to run
            parsed: Parsed content dictionary
            html: Raw HTML string
            url: URL of the page
            **context: Additional context

        Returns:
            AuditResult or None if audit not found
        """
        audit = self._audits.get(audit_id)
        if audit is None:
            return None
        return audit.run(parsed, html, url, **context)

    def run_category(
        self,
        category: str,
        parsed: dict,
        html: str,
        url: str,
        **context
    ) -> list[AuditResult]:
        """Run all audits in a category.

        Args:
            category: Category name
            parsed: Parsed content dictionary
            html: Raw HTML string
            url: URL of the page
            **context: Additional context

        Returns:
            List of AuditResults
        """
        audits = self.get_by_category(category)
        return [
            audit.run(parsed, html, url, **context)
            for audit in audits
        ]

    def run_all(
        self,
        parsed: dict,
        html: str,
        url: str,
        **context
    ) -> list[AuditResult]:
        """Run all registered audits.

        Args:
            parsed: Parsed content dictionary
            html: Raw HTML string
            url: URL of the page
            **context: Additional context

        Returns:
            List of all AuditResults
        """
        return [
            audit.run(parsed, html, url, **context)
            for audit in self._audits.values()
        ]


# Global registry instance
audit_registry = AuditRegistry()
