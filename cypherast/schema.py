"""Optional graph schema + function signature registry."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PropertyDef:
    name: str
    type: str
    mandatory: bool = False


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
    labels: dict[str, LabelDef] = field(default_factory=dict)
    rel_types: dict[str, RelTypeDef] = field(default_factory=dict)
    indexes: list[IndexDef] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)  # cardinality hints

    def add_label(self, name: str, **props: str) -> None:
        ld = self.labels.setdefault(name, LabelDef(name=name))
        for k, typ in props.items():
            ld.properties[k] = PropertyDef(name=k, type=typ)

    def add_rel(self, name: str, start: str, end: str, **props: str) -> None:
        rd = self.rel_types.setdefault(name, RelTypeDef(name=name))
        rd.endpoints.append((start, end))
        for k, typ in props.items():
            rd.properties[k] = PropertyDef(name=k, type=typ)


# Built-in Cypher function signatures: name -> (arg_types, return_type)
FUNCTION_SIGNATURES: dict[str, tuple[list[str], str]] = {
    "count": (["any"], "integer"),
    "sum": (["number"], "number"),
    "avg": (["number"], "float"),
    "min": (["any"], "any"),
    "max": (["any"], "any"),
    "collect": (["any"], "list"),
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
    "sin": (["number"], "float"),
    "cos": (["number"], "float"),
    "tan": (["number"], "float"),
    "replace": (["string", "string", "string"], "string"),
    "substring": (["string", "integer"], "string"),
    "trim": (["string"], "string"),
    "toLower": (["string"], "string"),
    "toUpper": (["string"], "string"),
    "split": (["string", "string"], "list"),
    "reverse": (["any"], "any"),
    "nodes": (["path"], "list"),
    "relationships": (["path"], "list"),
    "startNode": (["relationship"], "node"),
    "endNode": (["relationship"], "node"),
    "shortestPath": (["pattern"], "path"),
    "allShortestPaths": (["pattern"], "list"),
}


def lookup_function(name: str) -> tuple[list[str], str] | None:
    return FUNCTION_SIGNATURES.get(name) or FUNCTION_SIGNATURES.get(name.lower())


def modern_graph_schema() -> GraphSchema:
    """Small person/software tutorial schema (knows, created).

    Used as PuppyGraph's default when callers omit ``schema=`` so
    ``()-[e:knows]->()`` can be auto-labelled during optimize.
    """
    s = GraphSchema()
    s.add_label("person")
    s.labels["person"].properties["name"] = PropertyDef(name="name", type="string")
    s.labels["person"].properties["age"] = PropertyDef(name="age", type="integer")
    s.labels["person"].properties["status"] = PropertyDef(name="status", type="string")
    s.add_label("software")
    s.labels["software"].properties["name"] = PropertyDef(name="name", type="string")
    s.labels["software"].properties["lang"] = PropertyDef(name="lang", type="string")
    s.add_rel("knows", "person", "person", weight="float")
    s.add_rel("created", "person", "software")
    return s
