"""Evidence normalisers: every text format -> EvidenceRow, indexed by EvidenceIndex."""
from .base import EvidenceRow, system_for
from .index import EvidenceIndex, build_evidence_index

__all__ = ["EvidenceRow", "EvidenceIndex", "build_evidence_index", "system_for"]
