"""Read-only replay of source-bound derived amendment inventory descriptors.

This verifies the current parser's complete result against retained original
index bytes. Neither the descriptor nor successful replay establishes an act's
legal effect, a complete legal inventory, approval or production readiness.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import hashlib
import json
from pathlib import Path

from app.services.ett_amendment_inventory import parse_amendment_inventory
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_index import INDEX_URL, MAX_INDEX_BYTES
from app.services.ett_manifest import ETTManifest, ETTParserIdentity, validate_manifest

MAX_DERIVED_REPORT_BYTES = 16 * 1024 * 1024
_PARSER_COMPONENTS = ("ett_amendment_inventory.py", "ett_index.py", "ett_derived_inventory.py")


class DerivedInventoryError(ValueError):
    """A descriptor cannot be replayed against retained source bytes."""


def supported_inventory_parser_identity() -> ETTParserIdentity:
    """Fingerprint the supported parser, index dependency and encoding/replay."""
    try:
        root = Path(__file__).parent
        components = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in _PARSER_COMPONENTS}
    except OSError:
        raise DerivedInventoryError("derived inventory parser identity is unavailable") from None
    encoded = json.dumps(components, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ETTParserIdentity(name="ett-index-amendment-inventory", version="1",
                             sha256=hashlib.sha256(encoded).hexdigest())


def canonical_inventory_report_bytes(original_index: bytes) -> bytes:
    """Re-run the parser and encode its entire result, including unverified flags.

    Dates here are quoted adoption dates. The encoding matches the existing
    analysis inventory objects: sorted compact UTF-8 JSON without a newline.
    """
    if type(original_index) is not bytes or not 1 <= len(original_index) <= MAX_INDEX_BYTES:
        raise DerivedInventoryError("derived inventory original index size is invalid")

    def calendar(value):
        if type(value) is date:
            return value.isoformat()
        raise TypeError("unsupported inventory result value")

    try:
        result = asdict(parse_amendment_inventory(original_index))
        output = bytearray()
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                   allow_nan=False, default=calendar)
        for chunk in encoder.iterencode(result):
            encoded = chunk.encode("utf-8")
            if len(output) + len(encoded) > MAX_DERIVED_REPORT_BYTES:
                raise DerivedInventoryError("derived inventory report exceeds its size bound")
            output.extend(encoded)
        return bytes(output)
    except DerivedInventoryError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DerivedInventoryError("derived inventory original index cannot be replayed") from None


def verify_derived_amendment_inventory(manifest: ETTManifest, store: LocalArtifactStore) -> None:
    """Verify both original and derived objects before staging or stored preview.

    This function never fetches or writes. Byte comparison with a freshly
    encoded result rejects fabricated/rehashed reports, unknown fields,
    duplicate keys, type changes and claimed legal-verification flags alike.
    """
    validated = validate_manifest(manifest)
    binding = validated.derived_amendment_inventory
    if binding is None:
        return
    identity = supported_inventory_parser_identity()
    if binding.parser != identity:
        raise DerivedInventoryError("derived inventory parser identity does not match the supported parser")
    source = next(artifact for artifact in validated.artifacts if artifact.artifact_id == binding.source_artifact_id)
    if source.url != INDEX_URL or source.size_bytes > MAX_INDEX_BYTES:
        raise DerivedInventoryError("derived inventory source is not the actual official ETT index")
    original = store.read(source.sha256)
    retained_report = store.read(binding.report_sha256)
    if (len(original) != source.size_bytes or hashlib.sha256(original).hexdigest() != binding.source_artifact_sha256
            or len(retained_report) != binding.report_size_bytes
            or hashlib.sha256(retained_report).hexdigest() != binding.report_sha256):
        raise DerivedInventoryError("derived inventory source or report integrity failure")
    regenerated = canonical_inventory_report_bytes(original)
    if regenerated != retained_report:
        raise DerivedInventoryError("derived inventory report does not match the complete replayed result")
    if supported_inventory_parser_identity() != identity:
        raise DerivedInventoryError("derived inventory parser changed during replay")
