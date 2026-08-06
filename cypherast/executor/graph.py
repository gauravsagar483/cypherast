"""In-memory property graph."""

from __future__ import annotations

import itertools
import typing as t
from dataclasses import dataclass, field


@dataclass
class Node:
    id: int
    labels: set[str] = field(default_factory=set)
    props: dict[str, t.Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> t.Any:
        return self.props.get(key)

    def get(self, key: str, default: t.Any = None) -> t.Any:
        return self.props.get(key, default)


@dataclass
class Relationship:
    id: int
    type: str
    start: int
    end: int
    props: dict[str, t.Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> t.Any:
        return self.props.get(key)


class Graph:
    """Mutable in-memory property graph with adjacency indexes."""

    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}
        self.relationships: dict[int, Relationship] = {}
        self._out: dict[int, list[int]] = {}
        self._in: dict[int, list[int]] = {}
        self._by_label: dict[str, set[int]] = {}
        self._id_gen = itertools.count(1)

    def create_node(
        self, labels: t.Iterable[str] | None = None, **props: t.Any
    ) -> Node:
        nid = next(self._id_gen)
        lab = set(labels or [])
        node = Node(id=nid, labels=lab, props=dict(props))
        self.nodes[nid] = node
        for l in lab:
            self._by_label.setdefault(l, set()).add(nid)
        self._out.setdefault(nid, [])
        self._in.setdefault(nid, [])
        return node

    def create_rel(
        self,
        start: int | Node,
        end: int | Node,
        type: str,
        **props: t.Any,
    ) -> Relationship:
        s = start.id if isinstance(start, Node) else start
        e = end.id if isinstance(end, Node) else end
        rid = next(self._id_gen)
        rel = Relationship(id=rid, type=type, start=s, end=e, props=dict(props))
        self.relationships[rid] = rel
        self._out.setdefault(s, []).append(rid)
        self._in.setdefault(e, []).append(rid)
        return rel

    def delete_node(self, nid: int, detach: bool = False) -> None:
        if nid not in self.nodes:
            return
        if detach:
            for rid in list(self._out.get(nid, [])) + list(self._in.get(nid, [])):
                self.delete_rel(rid)
        elif self._out.get(nid) or self._in.get(nid):
            raise ValueError(f"Cannot delete node {nid} with relationships; use DETACH")
        node = self.nodes.pop(nid)
        for l in node.labels:
            self._by_label.get(l, set()).discard(nid)

    def delete_rel(self, rid: int) -> None:
        rel = self.relationships.pop(rid, None)
        if rel is None:
            return
        if rid in self._out.get(rel.start, []):
            self._out[rel.start].remove(rid)
        if rid in self._in.get(rel.end, []):
            self._in[rel.end].remove(rid)

    def nodes_with_label(self, label: str) -> list[Node]:
        return [self.nodes[i] for i in self._by_label.get(label, set()) if i in self.nodes]

    def all_nodes(self) -> list[Node]:
        return list(self.nodes.values())

    def out_rels(self, nid: int, typ: str | None = None) -> list[Relationship]:
        rels = [self.relationships[r] for r in self._out.get(nid, []) if r in self.relationships]
        if typ:
            rels = [r for r in rels if r.type == typ]
        return rels

    def in_rels(self, nid: int, typ: str | None = None) -> list[Relationship]:
        rels = [self.relationships[r] for r in self._in.get(nid, []) if r in self.relationships]
        if typ:
            rels = [r for r in rels if r.type == typ]
        return rels
