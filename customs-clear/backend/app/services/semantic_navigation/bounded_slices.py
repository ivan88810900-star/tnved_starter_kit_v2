"""Exact source/topology signatures for deliberately bounded semantic slices.

These constants are evidence for named, fail-closed exceptions.  They are not
generic extraction policy and must not be widened without a new source audit.
"""

from __future__ import annotations

PDO_2204_HEADING = "2204"
PDO_2204_PARENT_CODE = "2204210000"
PDO_2204_ANCHOR_CODE = "2204210900"
PDO_2204_STOP_CODE = "2204217800"
PDO_2204_DEPTH = 6
PDO_2204_REASON = "bounded_2204_official_pdo_chain"
PDO_2204_SCOPE_KIND = "canonical_sibling_leaf_interval"
PDO_2204_TITLE = "вина с защищенным наименованием по происхождению"
PDO_2204_OFFICIAL_HEADER = (
    "вина с защищенным наименованием по происхождению "
    "(Protected Designation of Origin, PDO)"
)
PGI_2204_TITLE = "вина с защищенным географическим указанием"
PGI_2204_OFFICIAL_HEADER = (
    "вина с защищенным географическим указанием "
    "(Protected Geographical Indication, PGI)"
)

# Audited against the Gate-2 Canonical snapshot.  Comparing the entire tuple
# prevents an interior deletion/substitution from satisfying only count and
# endpoint checks.
PDO_2204_CODES = (
    "2204211100",
    "2204211200",
    "2204211300",
    "2204211700",
    "2204211800",
    "2204211900",
    "2204212200",
    "2204212300",
    "2204212400",
    "2204212600",
    "2204212700",
    "2204212800",
    "2204213200",
    "2204213400",
    "2204213600",
    "2204213700",
    "2204213800",
    "2204214200",
    "2204214300",
    "2204214400",
    "2204214600",
    "2204214700",
    "2204214800",
    "2204216200",
    "2204216600",
    "2204216700",
    "2204216800",
    "2204216900",
    "2204217100",
    "2204217400",
    "2204217600",
    "2204217700",
    PDO_2204_STOP_CODE,
)
PDO_2204_FIRST_CODE = PDO_2204_CODES[0]
PDO_2204_LEAF_COUNT = len(PDO_2204_CODES)
