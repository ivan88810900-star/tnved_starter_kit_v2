"""Tree Model v2 — параллельный движок дерева ТН ВЭД (не подключён к API)."""

from .builder import TreeBuilder
from .canonical_model import CanonicalModel, CanonicalModelValidationError
from .flags import (
    is_canonical_tree_enabled,
    is_canonical_tree_shadow_enabled,
)
from .models import (
    ClassificationGroupNode,
    CommodityNode,
    HeadingNode,
    NodeType,
    ParsedCommodityRecord,
    TreeNode,
    TreeParseResult,
    assign_stable_ids,
    compute_snapshot_id,
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
    ShadowComparison,
    children_fingerprint,
    compare_children,
    node_fingerprint,
)
from .validator import TreeValidator, ValidationIssue, ValidationResult

__all__ = [
    "CanonicalModel",
    "CanonicalModelValidationError",
    "CanonicalTreeProvider",
    "ClassificationGroupNode",
    "CommodityNode",
    "HeadingNode",
    "NodeType",
    "ParsedCommodityRecord",
    "RecoveredHeading",
    "RecoveredNode",
    "ShadowComparison",
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
    "get_canonical_model",
    "get_provider",
    "is_canonical_tree_enabled",
    "is_canonical_tree_shadow_enabled",
    "node_fingerprint",
    "reset_canonical_provider",
]
