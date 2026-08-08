"""Optional graph schema + function signature registry.

Callers pass ``GraphSchema`` into ``optimize`` / ``validate`` (same role as a
relational column catalog for SQL optimizers — graph labels, rel types,
properties, and id-field markers).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PropertyDef:
    name: str
    type: str
    mandatory: bool = False
    # True → not a queryable map property; use id()/elementId() instead
    id_field: bool = False


@dataclass
class LabelDef:
    name: str
    properties: dict[str, PropertyDef] = field(default_factory=dict)


@dataclass
class RelTypeDef:
    name: str
    properties: dict[str, PropertyDef] = field(default_factory=dict)
    endpoints: list[tuple[str, str]] = field(default_factory=list)  # (from_label, to_label)


@dataclass
class IndexDef:
    label: str
    properties: list[str]
    unique: bool = False


@dataclass
class GraphSchema:
    """In-memory graph catalog: labels, rel types, properties, optional stats.

    When passed to ``optimize`` / ``validate``:
    - ``id_field`` properties are rejected (use ``id(n)`` / ``elementId(n)``)
    - when ``strict``: unknown labels (CG1301), unknown rel types (CG1302),
      and undeclared properties on known labels/rels (CG1303)
    - when not ``strict``: unknown labels/types ignored (open-world)
    """

    labels: dict[str, LabelDef] = field(default_factory=dict)
    rel_types: dict[str, RelTypeDef] = field(default_factory=dict)
    indexes: list[IndexDef] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)  # cardinality hints
    # When True: closed-world catalog — unknown labels/rel types + undeclared
    # props on known names are rejected. Default False keeps open-world ignore
    # for unknown names (callers pass schema= when they need a catalog).
    strict: bool = False

    def add_label(self, label: str, **props: str) -> None:
        """Register label; kwargs are ``prop_name=type`` (not id fields)."""
        ld = self.labels.setdefault(label, LabelDef(name=label))
        for k, typ in props.items():
            ld.properties[k] = PropertyDef(name=k, type=typ)

    def add_id_field(self, label: str, prop: str, typ: str = "string") -> None:
        """Mark ``label.prop`` as vertex id storage — not queryable via ``n.prop``."""
        ld = self.labels.setdefault(label, LabelDef(name=label))
        ld.properties[prop] = PropertyDef(name=prop, type=typ, id_field=True)

    def add_rel_id_field(self, rel_type: str, prop: str, typ: str = "string") -> None:
        """Mark ``rel_type.prop`` as edge id storage — not queryable via ``r.prop``."""
        rd = self.rel_types.setdefault(rel_type, RelTypeDef(name=rel_type))
        rd.properties[prop] = PropertyDef(name=prop, type=typ, id_field=True)

    def add_rel(self, name: str, start: str, end: str, **props: str) -> None:
        rd = self.rel_types.setdefault(name, RelTypeDef(name=name))
        rd.endpoints.append((start, end))
        for k, typ in props.items():
            rd.properties[k] = PropertyDef(name=k, type=typ)

    def has_label(self, name: str) -> bool:
        return self._find_label(name) is not None

    def has_rel(self, name: str) -> bool:
        return self._find_rel(name) is not None

    def property_names(self, label: str, *, include_id_fields: bool = False) -> list[str]:
        ld = self._find_label(label)
        if ld is None:
            return []
        return [p.name for p in ld.properties.values() if include_id_fields or not p.id_field]

    def has_property(self, label: str, prop: str) -> bool:
        pd = self.get_property(label, prop)
        return pd is not None and not pd.id_field

    def is_id_property(self, label: str, prop: str) -> bool:
        pd = self.get_property(label, prop)
        return pd is not None and pd.id_field

    def get_property(self, label: str, prop: str) -> PropertyDef | None:
        ld = self._find_label(label)
        if ld is None:
            return None
        if prop in ld.properties:
            return ld.properties[prop]
        for k, v in ld.properties.items():
            if k.lower() == prop.lower():
                return v
        return None

    def has_rel_property(self, rel_type: str, prop: str) -> bool:
        pd = self.get_rel_property(rel_type, prop)
        return pd is not None and not pd.id_field

    def is_rel_id_property(self, rel_type: str, prop: str) -> bool:
        pd = self.get_rel_property(rel_type, prop)
        return pd is not None and pd.id_field

    def get_rel_property(self, rel_type: str, prop: str) -> PropertyDef | None:
        rd = self._find_rel(rel_type)
        if rd is None:
            return None
        if prop in rd.properties:
            return rd.properties[prop]
        for k, v in rd.properties.items():
            if k.lower() == prop.lower():
                return v
        return None

    def get_property_type(self, label: str, prop: str) -> str | None:
        pd = self.get_property(label, prop)
        return pd.type if pd and not pd.id_field else None

    def _find_label(self, name: str) -> LabelDef | None:
        if name in self.labels:
            return self.labels[name]
        for k, v in self.labels.items():
            if k.lower() == name.lower():
                return v
        return None

    def _find_rel(self, name: str) -> RelTypeDef | None:
        if name in self.rel_types:
            return self.rel_types[name]
        for k, v in self.rel_types.items():
            if k.lower() == name.lower():
                return v
        return None


def ensure_schema(schema: object | None) -> GraphSchema | None:
    """Normalize caller schema input to ``GraphSchema`` or ``None``."""
    if schema is None:
        return None
    if isinstance(schema, GraphSchema):
        return schema
    raise TypeError(f"schema must be GraphSchema or None, got {type(schema).__name__}")


# Built-in Cypher function signatures: name -> (arg_types, return_type)
FUNCTION_SIGNATURES: dict[str, tuple[list[str], str]] = {
    "count": (["any"], "integer"),
    "sum": (["number"], "number"),
    "avg": (["number"], "float"),
    "min": (["any"], "any"),
    "max": (["any"], "any"),
    "collect": (["any"], "list"),
    "percentileCont": (["float", "number"], "float"),
    "percentileDisc": (["float", "number"], "float"),
    "stdev": (["number"], "float"),
    "stdevP": (["number"], "float"),
    "size": (["any"], "integer"),
    "length": (["path"], "integer"),
    "type": (["relationship"], "string"),
    "labels": (["node"], "list"),
    "keys": (["any"], "list"),
    "properties": (["any"], "map"),
    "id": (["any"], "integer"),
    "elementId": (["any"], "string"),
    "coalesce": (["any"], "any"),
    "head": (["list"], "any"),
    "last": (["list"], "any"),
    "tail": (["list"], "list"),
    "range": (["integer", "integer"], "list"),
    "toString": (["any"], "string"),
    "toInteger": (["any"], "integer"),
    "toFloat": (["any"], "float"),
    "toBoolean": (["any"], "boolean"),
    "abs": (["number"], "number"),
    "ceil": (["number"], "integer"),
    "floor": (["number"], "integer"),
    "round": (["number"], "number"),
    "sqrt": (["number"], "float"),
    "sign": (["number"], "integer"),
    "exp": (["number"], "float"),
    "log": (["number"], "float"),
    "log10": (["number"], "float"),
    "e": ([], "float"),
    "pi": ([], "float"),
    "rand": ([], "float"),
    "timestamp": ([], "integer"),
    "sin": (["number"], "float"),
    "cos": (["number"], "float"),
    "tan": (["number"], "float"),
    "acos": (["number"], "float"),
    "asin": (["number"], "float"),
    "atan": (["number"], "float"),
    "atan2": (["number", "number"], "float"),
    "cot": (["number"], "float"),
    "degrees": (["number"], "float"),
    "radians": (["number"], "float"),
    "replace": (["string", "string", "string"], "string"),
    "substring": (["string", "integer", "integer"], "string"),
    "left": (["string", "integer"], "string"),
    "right": (["string", "integer"], "string"),
    "trim": (["string"], "string"),
    "lTrim": (["string"], "string"),
    "rTrim": (["string"], "string"),
    "toLower": (["string"], "string"),
    "toUpper": (["string"], "string"),
    "split": (["string", "string"], "list"),
    "reverse": (["any"], "any"),
    "nodes": (["path"], "list"),
    "relationships": (["path"], "list"),
    "startNode": (["path"], "node"),
    "endNode": (["path"], "node"),
    "shortestPath": (["pattern"], "path"),
    "allShortestPaths": (["pattern"], "list"),
}

# Alternate names → canonical registry key (lowercase keys)
FUNCTION_ALIASES: dict[str, str] = {
    "rels": "relationships",
    "lower": "toLower",
    "upper": "toUpper",
}

# Variadic / optional-argument helpers for validation
FUNCTION_VARIADIC_MIN: dict[str, int] = {"coalesce": 1}
FUNCTION_OPTIONAL_ARGS: dict[str, int] = {"substring": 1, "range": 1}

# Excluded from openCypher 9 (standardisation-scope.adoc)
OC9_EXCLUDED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "exists",
        "all",
        "any",
        "none",
        "single",
        "filter",
        "extract",
        "reduce",
        "distance",
        "point",
        "haversin",
    }
)

_SIG_LOWER: dict[str, tuple[list[str], str]] = {
    k.lower(): v for k, v in FUNCTION_SIGNATURES.items()
}


def canonicalize_function_name(name: str) -> str | None:
    """Resolve aliases and case variants to a registry key, or None."""
    if name in FUNCTION_SIGNATURES:
        return name
    lower = name.lower()
    if lower in FUNCTION_ALIASES:
        return FUNCTION_ALIASES[lower]
    for key in FUNCTION_SIGNATURES:
        if key.lower() == lower:
            return key
    return None


def lookup_function(name: str) -> tuple[list[str], str] | None:
    canon = canonicalize_function_name(name)
    if canon is not None:
        return FUNCTION_SIGNATURES[canon]
    return _SIG_LOWER.get(name.lower())
