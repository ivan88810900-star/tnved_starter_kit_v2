"""Canonical tree engine; `/children` read-path доступен только за default-OFF флагом."""

from .builder import TreeBuilder
from .canonical_model import CanonicalModel, CanonicalModelValidationError
from .flags import (
    is_canonical_tree_enabled,
    is_canonical_tree_shadow_enabled,
)
from .models import (
    CanonicalAnchor,
    CanonicalSourceRecord,
    ClassificationGroupNode,
    CommodityNode,
    HeadingNode,
    NodeType,
    ParsedCommodityRecord,
    TreeNode,
    TreeParseResult,
    assign_stable_ids,
    compute_snapshot_id,
    stamp_snapshot_id,
)
from .parser import TreeParser
from .provider import (
    CanonicalTreeProvider,
    get_canonical_model,
    get_provider,
    reset_canonical_provider,
)
from .recovery import RecoveredHeading, RecoveredNode, StructureNormalizer
from .serializer import TreeSerializer
from .shadow import (
    DEFAULT_MISMATCH_LOG_EVERY,
    ShadowComparison,
    ShadowMetricsSnapshot,
    ShadowMonitor,
    children_fingerprint,
    compare_children,
    get_shadow_metrics,
    node_fingerprint,
    record_shadow_comparison,
    reset_shadow_metrics,
)
from .validator import TreeValidator, ValidationIssue, ValidationResult

__all__ = [
    "CanonicalModel",
    "CanonicalAnchor",
    "CanonicalSourceRecord",
    "CanonicalModelValidationError",
    "CanonicalTreeProvider",
    "ClassificationGroupNode",
    "CommodityNode",
    "DEFAULT_MISMATCH_LOG_EVERY",
    "HeadingNode",
    "NodeType",
    "ParsedCommodityRecord",
    "RecoveredHeading",
    "RecoveredNode",
    "ShadowComparison",
    "ShadowMetricsSnapshot",
    "ShadowMonitor",
    "StructureNormalizer",
    "TreeBuilder",
    "TreeNode",
    "TreeParseResult",
    "TreeParser",
    "TreeSerializer",
    "TreeValidator",
    "ValidationIssue",
    "ValidationResult",
    "assign_stable_ids",
    "children_fingerprint",
    "compare_children",
    "compute_snapshot_id",
    "stamp_snapshot_id",
    "get_canonical_model",
    "get_provider",
    "get_shadow_metrics",
    "is_canonical_tree_enabled",
    "is_canonical_tree_shadow_enabled",
    "node_fingerprint",
    "record_shadow_comparison",
    "reset_canonical_provider",
    "reset_shadow_metrics",
]
