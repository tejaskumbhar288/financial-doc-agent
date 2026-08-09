"""Anomaly Detection Agent — orchestrates anomaly detection rules."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.agents.anomaly_rules import (
    AnomalyResult,
    check_amount_mismatch,
    check_round_number_bias,
    check_date_anomalies,
)
from app.models.anomaly import AnomalyFlag, AnomalySeverity
from app.models.document import ExtractedDocument
from app.schemas.invoice import InvoiceExtraction
from app.schemas.receipt import ReceiptExtraction


class AnomalyDetectionAgent:
    """
    Orchestrates anomaly detection rules and persists findings.

    Runs deterministic checks on an extracted document and writes flagged
    anomalies to the database for audit trail and review queue.
    """

    def __init__(self, db_session: Session):
        """
        Initialize the agent with a database session.

        Args:
            db_session: SQLAlchemy session for writing findings
        """
        self.db = db_session

    def run(self, extraction: InvoiceExtraction | ReceiptExtraction) -> dict:
        """
        Run all anomaly detection rules on an extraction.

        Args:
            extraction: The extracted document to check

        Returns:
            dict with:
            - findings: list of AnomalyResult objects
            - flagged_count: number of anomalies flagged
            - highest_severity: most severe anomaly level
        """
        findings = []

        # Run all three deterministic rules (no history needed)
        findings.append(check_amount_mismatch(extraction))
        findings.append(
            check_round_number_bias(
                extraction, approval_threshold=Decimal("5000")
            )
        )
        findings.append(check_date_anomalies(extraction))

        # Separate flagged findings from clean results
        flagged_findings = [f for f in findings if f.flagged]

        # Determine highest severity
        highest_severity = None
        if flagged_findings:
            severity_order = {
                AnomalySeverity.CRITICAL: 4,
                AnomalySeverity.HIGH: 3,
                AnomalySeverity.MEDIUM: 2,
                AnomalySeverity.LOW: 1,
            }
            highest_severity = max(
                (f.severity for f in flagged_findings if f.severity),
                key=lambda s: severity_order.get(s, 0),
                default=None,
            )

        return {
            "findings": findings,
            "flagged_findings": flagged_findings,
            "flagged_count": len(flagged_findings),
            "highest_severity": highest_severity,
            "status": "anomalies_detected" if flagged_findings else "clean",
        }

    def persist_findings(
        self, extraction: InvoiceExtraction | ReceiptExtraction, findings: list
    ) -> None:
        """
        Write anomaly findings to the database.

        Args:
            extraction: The extraction that was checked
            findings: List of AnomalyResult objects to persist
        """
        for finding in findings:
            if not finding.flagged:
                continue  # Only persist flagged anomalies

            # Create AnomalyFlag record
            flag = AnomalyFlag(
                document_id=str(extraction.document_id),
                rule_name=finding.rule_name,
                severity=finding.severity,
                description=finding.description,
                details=finding.details,
            )

            self.db.add(flag)

        self.db.commit()
