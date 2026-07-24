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
    MAX_SEMANTIC_GROUP_LEVELS,
    MAX_UNSPLIT_GROUP_CODES,
    REAL_CODE_NODE_TYPES,
    NestingFallback,
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
    "GROUP_NODE_TYPES",
    "HIGH",
    "LOW",
    "MAX_SEMANTIC_GROUP_LEVELS",
    "MAX_UNSPLIT_GROUP_CODES",
    "MEDIUM",
    "REAL_CODE_NODE_TYPES",
    "WARNING",
    "ExtractedGroup",
    "ExtractionResult",
    "NestingFallback",
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
