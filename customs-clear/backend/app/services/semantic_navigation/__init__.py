"""Semantic Navigation v1 — экспериментальный слой смысловой навигации по ТН ВЭД.

Изолированный домен: не подключён к production API, frontend и _build_tree().
"""

from .builder import SemanticNavigationBuilder
from .extractor import (
    HIGH,
    LOW,
    MEDIUM,
    ExtractedGroup,
    ExtractionResult,
    RejectedCandidate,
    SemanticStructureExtractor,
)
from .models import (
    GROUP_NODE_TYPES,
    REAL_CODE_NODE_TYPES,
    SemanticNavigationTree,
    SemanticNode,
    SemanticNodeType,
    SourceRecord,
)
from .serializer import SemanticNavigationSerializer
from .validator import (
    CRITICAL,
    WARNING,
    SemanticIssue,
    SemanticNavigationValidator,
    SemanticValidationResult,
)

__all__ = [
    "CRITICAL",
    "HIGH",
    "LOW",
    "MEDIUM",
    "WARNING",
    "ExtractedGroup",
    "ExtractionResult",
    "GROUP_NODE_TYPES",
    "REAL_CODE_NODE_TYPES",
    "RejectedCandidate",
    "SemanticIssue",
    "SemanticNavigationBuilder",
    "SemanticNavigationSerializer",
    "SemanticNavigationTree",
    "SemanticNavigationValidator",
    "SemanticNode",
    "SemanticNodeType",
    "SemanticStructureExtractor",
    "SemanticValidationResult",
    "SourceRecord",
]
