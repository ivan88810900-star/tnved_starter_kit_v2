"""Exact source/topology signatures for deliberately bounded semantic slices.

These constants are evidence for named, fail-closed exceptions.  They are not
generic extraction policy and must not be widened without a new source audit.
"""

from __future__ import annotations

from dataclasses import dataclass


STATE_0304_HEADING = "0304"
STATE_0304_PAD_CODE = "0304000000"
STATE_0304_REASON = "bounded_0304_official_fish_state"
STATE_0304_SCOPE_KIND = "canonical_exact_code_topology"


@dataclass(frozen=True)
class Bounded0304GroupSpec:
    """One official level-1 state proven against the Gate-2 snapshot."""

    key: str
    anchor_code: str
    title: str
    code_prefix: str
    signature: tuple[tuple[str, str, bool], ...]
    generic_disposition: str  # accepted | rejected

    @property
    def last_code(self) -> str:
        return self.signature[-1][0]

    @property
    def leaf_count(self) -> int:
        return sum(is_leaf for _, _, is_leaf in self.signature)


# This is deliberately a complete, ordered (code, Canonical parent, leaf)
# signature rather than a range/count heuristic.  The five official headers
# describe mutually exclusive product states in heading 0304.  A source or
# topology change in any one state disables the complete bounded overlay.
STATE_0304_GROUPS = (
    Bounded0304GroupSpec(
        key="A",
        anchor_code="0304390000",
        title="филе прочей рыбы, свежее или охлажденное",
        code_prefix="03044",
        generic_disposition="accepted",
        signature=(
            ("0304410000", "0304", True),
            ("0304420000", "0304", False),
            ("0304421000", "0304420000", True),
            ("0304425000", "0304420000", True),
            ("0304429000", "0304420000", True),
            ("0304430000", "0304", True),
            ("0304440000", "0304", False),
            ("0304441000", "0304440000", True),
            ("0304443000", "0304440000", True),
            ("0304449000", "0304440000", True),
            ("0304450000", "0304", True),
            ("0304460000", "0304", True),
            ("0304470000", "0304", True),
            ("0304480000", "0304", True),
            ("0304490000", "0304", False),
            ("0304491010", "0304490000", True),
            ("0304491080", "0304490000", True),
            ("0304495000", "0304490000", True),
            ("0304498000", "0304490000", True),
        ),
    ),
    Bounded0304GroupSpec(
        key="B",
        anchor_code="0304498000",
        title="прочее, свежее или охлажденное",
        code_prefix="03045",
        generic_disposition="rejected",
        signature=(
            ("0304510000", "0304", True),
            ("0304520000", "0304", True),
            ("0304530000", "0304", True),
            ("0304540000", "0304", True),
            ("0304550000", "0304", True),
            ("0304560000", "0304", True),
            ("0304570000", "0304", True),
            ("0304590000", "0304", False),
            ("0304592000", "0304590000", True),
            ("0304595000", "0304590000", True),
            ("0304598000", "0304590000", True),
        ),
    ),
    Bounded0304GroupSpec(
        key="C",
        anchor_code="0304690000",
        title=(
            "филе мороженое рыбы семейств Bregmacerotidae, Euclichthyidae, "
            "Gadidae, Macrouridae, Melanonidae, Merlucciidae, Moridae и "
            "Muraenolepididae"
        ),
        code_prefix="03047",
        generic_disposition="accepted",
        signature=(
            ("0304710000", "0304", False),
            ("0304711000", "0304710000", True),
            ("0304719000", "0304710000", True),
            ("0304720000", "0304", True),
            ("0304730000", "0304", True),
            ("0304740000", "0304", False),
            ("0304741100", "0304740000", True),
            ("0304741500", "0304740000", True),
            ("0304741900", "0304740000", True),
            ("0304749000", "0304740000", True),
            ("0304750000", "0304", True),
            ("0304790000", "0304", False),
            ("0304791000", "0304790000", True),
            ("0304793000", "0304790000", True),
            ("0304795000", "0304790000", True),
            ("0304798000", "0304790000", True),
            ("0304799000", "0304790000", True),
        ),
    ),
    Bounded0304GroupSpec(
        key="D",
        anchor_code="0304799000",
        title="филе прочей рыбы, мороженое",
        code_prefix="03048",
        generic_disposition="accepted",
        signature=(
            ("0304810000", "0304", True),
            ("0304820000", "0304", False),
            ("0304821000", "0304820000", True),
            ("0304825000", "0304820000", True),
            ("0304829000", "0304820000", True),
            ("0304830000", "0304", False),
            ("0304831000", "0304830000", True),
            ("0304833000", "0304830000", True),
            ("0304835000", "0304830000", True),
            ("0304839000", "0304830000", True),
            ("0304840000", "0304", True),
            ("0304850000", "0304", True),
            ("0304860000", "0304", True),
            ("0304870000", "0304", True),
            ("0304880000", "0304", False),
            ("0304881000", "0304880000", True),
            ("0304882000", "0304880000", True),
            ("0304885000", "0304880000", True),
            ("0304889000", "0304880000", True),
            ("0304890000", "0304", False),
            ("0304891010", "0304890000", True),
            ("0304891080", "0304890000", True),
            ("0304892100", "0304890000", True),
            ("0304892900", "0304890000", True),
            ("0304893000", "0304890000", True),
            ("0304894100", "0304890000", True),
            ("0304894900", "0304890000", True),
            ("0304896000", "0304890000", True),
            ("0304898000", "0304890000", True),
        ),
    ),
    Bounded0304GroupSpec(
        key="E",
        anchor_code="0304898000",
        title="прочее, мороженое",
        code_prefix="03049",
        generic_disposition="rejected",
        signature=(
            ("0304910000", "0304", True),
            ("0304920000", "0304", True),
            ("0304930000", "0304", False),
            ("0304932000", "0304930000", True),
            ("0304938000", "0304930000", True),
            ("0304940000", "0304", False),
            ("0304941000", "0304940000", True),
            ("0304949000", "0304940000", True),
            ("0304950000", "0304", False),
            ("0304951000", "0304950000", True),
            ("0304952100", "0304950000", True),
            ("0304952500", "0304950000", True),
            ("0304952900", "0304950000", True),
            ("0304953000", "0304950000", True),
            ("0304954000", "0304950000", True),
            ("0304955000", "0304950000", True),
            ("0304956000", "0304950000", True),
            ("0304959000", "0304950000", True),
            ("0304960000", "0304", False),
            ("0304961000", "0304960000", True),
            ("0304969000", "0304960000", True),
            ("0304970000", "0304", False),
            ("0304971000", "0304970000", True),
            ("0304979000", "0304970000", True),
            ("0304990000", "0304", False),
            ("0304991100", "0304990000", True),
            ("0304992200", "0304990000", True),
            ("0304992300", "0304990000", True),
            ("0304992900", "0304990000", True),
            ("0304995500", "0304990000", True),
            ("0304996100", "0304990000", True),
            ("0304996500", "0304990000", True),
            ("0304999800", "0304990000", True),
        ),
    ),
)

# Real codes outside the five bounded spans are part of the same audited
# heading projection.  Keeping their Canonical role/parent evidence in the
# contract prevents a new in-prefix node (or a changed direct-node parent) from
# silently changing the meaning of an otherwise unchanged five-slice chain.
STATE_0304_FLAT_SIGNATURE = (
    ("0304310000", STATE_0304_HEADING, True),
    ("0304320000", STATE_0304_HEADING, True),
    ("0304330000", STATE_0304_HEADING, True),
    ("0304390000", STATE_0304_HEADING, True),
    ("0304610000", STATE_0304_HEADING, True),
    ("0304620000", STATE_0304_HEADING, True),
    ("0304630000", STATE_0304_HEADING, True),
    ("0304690000", STATE_0304_HEADING, True),
)

# Complete ordered non-pad projection: 109 nodes inside A-E plus the eight
# intentionally flat leaves above.  Prefixes/counts alone are not evidence.
STATE_0304_REAL_SIGNATURE = tuple(
    sorted(
        (
            *STATE_0304_FLAT_SIGNATURE,
            *(
                signature
                for spec in STATE_0304_GROUPS
                for signature in spec.signature
            ),
        ),
        key=lambda signature: signature[0],
    )
)

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


CHEESE_0406_HEADING = "0406"
CHEESE_0406_PAD_CODE = "0406000000"
CHEESE_0406_PARENT_CODE = "0406900000"
CHEESE_0406_ANCHOR_CODE = "0406905000"
CHEESE_0406_MIDDLE_ANCHOR_CODE = "0406906900"
CHEESE_0406_MIDDLE_STOP_CODE = "0406909200"
CHEESE_0406_STOP_CODE = "0406909300"
CHEESE_0406_AFTER_CODE = "0406909900"
CHEESE_0406_REASON = "bounded_0406_official_moisture_chain"
CHEESE_0406_SCOPE_KIND = "canonical_sibling_leaf_moisture_chain"
CHEESE_0406_TOP_TITLE = (
    "с содержанием жира не более 40 мас.% и содержанием влаги в "
    "обезжиренном веществе"
)
CHEESE_0406_LOW_TITLE = "не более 47 мас.%"
CHEESE_0406_MIDDLE_TITLE = "более 47 мас.%, но не более 72 мас.%"
CHEESE_0406_HIGH_TITLE = "более 72 мас.%"

# Exact strings produced by the current official-catalog import.  They are
# intentionally stricter than the generic extractor: any legal-text or packed
# marker drift disables the whole codeless chain until another source audit.
CHEESE_0406_ANCHOR_DESCRIPTION = (
    "– – – – сыры из овечьего молока или молока буйволиц в контейнерах, "
    "содержащих рассол, или в бурдюках из овечьей или козьей шкуры "
    "– – – – прочие: "
    f"– – – – – {CHEESE_0406_TOP_TITLE}: "
    f"– – – – – – {CHEESE_0406_LOW_TITLE}:"
)
CHEESE_0406_MIDDLE_DESCRIPTION = (
    "– – – – – – – прочие "
    f"– – – – – – {CHEESE_0406_MIDDLE_TITLE}:"
)
CHEESE_0406_STOP_DESCRIPTION = f"– – – – – – {CHEESE_0406_HIGH_TITLE}"
CHEESE_0406_AFTER_DESCRIPTION = "– – – – – прочие:"


@dataclass(frozen=True)
class Bounded0406GroupSpec:
    """One exact codeless wrapper in the audited 0406 moisture chain."""

    key: str
    title: str
    anchor_code: str
    stop_code: str
    dash_depth: int
    signature: tuple[tuple[str, str, bool], ...]

    @property
    def leaf_count(self) -> int:
        return len(self.signature)


CHEESE_0406_LOW_SIGNATURE = (
    ("0406906100", CHEESE_0406_PARENT_CODE, True),
    ("0406906300", CHEESE_0406_PARENT_CODE, True),
    ("0406906900", CHEESE_0406_PARENT_CODE, True),
)
CHEESE_0406_MIDDLE_SIGNATURE = (
    ("0406907300", CHEESE_0406_PARENT_CODE, True),
    ("0406907400", CHEESE_0406_PARENT_CODE, True),
    ("0406907500", CHEESE_0406_PARENT_CODE, True),
    ("0406907600", CHEESE_0406_PARENT_CODE, True),
    ("0406907800", CHEESE_0406_PARENT_CODE, True),
    ("0406907900", CHEESE_0406_PARENT_CODE, True),
    ("0406908100", CHEESE_0406_PARENT_CODE, True),
    ("0406908200", CHEESE_0406_PARENT_CODE, True),
    ("0406908400", CHEESE_0406_PARENT_CODE, True),
    ("0406908500", CHEESE_0406_PARENT_CODE, True),
    ("0406908600", CHEESE_0406_PARENT_CODE, True),
    ("0406908900", CHEESE_0406_PARENT_CODE, True),
    ("0406909200", CHEESE_0406_PARENT_CODE, True),
)
CHEESE_0406_HIGH_SIGNATURE = (
    (CHEESE_0406_STOP_CODE, CHEESE_0406_PARENT_CODE, True),
)
CHEESE_0406_TOP_SIGNATURE = (
    *CHEESE_0406_LOW_SIGNATURE,
    *CHEESE_0406_MIDDLE_SIGNATURE,
    *CHEESE_0406_HIGH_SIGNATURE,
)
CHEESE_0406_GROUPS = (
    Bounded0406GroupSpec(
        key="top",
        title=CHEESE_0406_TOP_TITLE,
        anchor_code=CHEESE_0406_ANCHOR_CODE,
        stop_code=CHEESE_0406_STOP_CODE,
        dash_depth=5,
        signature=CHEESE_0406_TOP_SIGNATURE,
    ),
    Bounded0406GroupSpec(
        key="low",
        title=CHEESE_0406_LOW_TITLE,
        anchor_code=CHEESE_0406_ANCHOR_CODE,
        stop_code=CHEESE_0406_MIDDLE_ANCHOR_CODE,
        dash_depth=6,
        signature=CHEESE_0406_LOW_SIGNATURE,
    ),
    Bounded0406GroupSpec(
        key="middle",
        title=CHEESE_0406_MIDDLE_TITLE,
        anchor_code=CHEESE_0406_MIDDLE_ANCHOR_CODE,
        stop_code=CHEESE_0406_MIDDLE_STOP_CODE,
        dash_depth=6,
        signature=CHEESE_0406_MIDDLE_SIGNATURE,
    ),
)
