"""Rewrite: ensure MATCH nodes carry labels from schema / query mining."""

from __future__ import annotations

import contextlib

from cypherast import ast as a
from cypherast.schema import GraphSchema, RelTypeDef


def ensure_labelled_nodes(
    tree: a.AstNode,
    schema: object | None = None,
) -> a.AstNode:
    """Fill missing MATCH node labels from schema + labels already in the query.

    1. Seed a working ``GraphSchema`` from ``schema`` (if any).
    2. Mine ``(Lab)-[:R]->(Lab)`` segments in this tree into that schema.
    3. Infer missing ends from typed relationships (fixpoint).

    Always runs (even when caller schema has no rel_types) so lineage-style
    queries that already name labels on some clauses can label the rest.
    """
    base = schema if isinstance(schema, GraphSchema) else GraphSchema()
    # Shallow working copy of rel endpoints (do not mutate caller schema)
    gs = GraphSchema()
    gs.labels = dict(base.labels)
    for name, rd in base.rel_types.items():
        gs.rel_types[name] = RelTypeDef(
            name=rd.name,
            properties=dict(rd.properties),
            endpoints=list(rd.endpoints),
        )

    # Avoid colliding with names qualify() already minted (_n_1, …).
    used_n = 0
    for ident in tree.find_all(a.Identifier):
        assert isinstance(ident, a.Identifier)
        text = str(ident.this or "")
        if text.startswith("_n_"):
            with contextlib.suppress(ValueError):
                used_n = max(used_n, int(text[3:]))
    counter = {"n": used_n}
    # Labels already bound to a variable in an earlier MATCH — reuse sites must
    # keep that label (never copy a neighbor's label onto a prior-bound var).
    var_labels: dict[str, set[str]] = {}

    def _name() -> str:
        counter["n"] += 1
        return f"_n_{counter['n']}"

    def _existing_labels(n: a.NodePattern) -> set[str]:
        if not isinstance(n.labels, a.LabelExpression):
            return set()
        if n.labels.expression:
            # OR expression person|software — treat as labelled, not expandable here
            return {str(n.labels.expression)}
        if n.labels.labels:
            return {str(x) for x in n.labels.labels}
        return set()

    def _var_name(n: a.NodePattern) -> str | None:
        if isinstance(n.variable, a.Identifier) and n.variable.this:
            return str(n.variable.this)
        return None

    def _apply_labels(n: a.NodePattern, cands: set[str]) -> bool:
        # Ignore OR-expression markers stored as single joined string with |
        clean = {c for c in cands if c and "|" not in c}
        if not clean or _existing_labels(n):
            return False
        # Drop expression-only "labelled" that was only a marker — if expression set, skip
        if isinstance(n.labels, a.LabelExpression) and n.labels.expression:
            return False
        if len(clean) == 1:
            n.labels = a.LabelExpression(labels=[next(iter(clean))])
        else:
            n.labels = a.LabelExpression(
                labels=[],
                expression="|".join(sorted(clean)),
            )
        if n.variable is None:
            n.variable = a.Identifier(this=_name())
        vn = _var_name(n)
        if vn:
            var_labels.setdefault(vn, set()).update(clean)
        return True

    def _rel_def(tname: str) -> RelTypeDef | None:
        rd = gs.rel_types.get(tname) or gs.rel_types.get(tname.lower())
        if rd is not None:
            return rd
        for k, v in gs.rel_types.items():
            if k.lower() == tname.lower():
                return v
        return None

    def _ensure_rel(tname: str) -> RelTypeDef:
        rd = _rel_def(tname)
        if rd is not None:
            return rd
        rd = RelTypeDef(name=tname)
        gs.rel_types[tname] = rd
        return rd

    def _mine_path(path: a.PathPattern) -> None:
        els = list(path.elements or [])
        i = 0
        while i + 2 < len(els):
            left, rel, right = els[i], els[i + 1], els[i + 2]
            if not (
                isinstance(left, a.NodePattern)
                and isinstance(rel, a.RelationshipPattern)
                and isinstance(right, a.NodePattern)
            ):
                i += 1
                continue
            types = [str(t) for t in (rel.types or [])]
            left_labs = {x for x in _existing_labels(left) if "|" not in x}
            right_labs = {x for x in _existing_labels(right) if "|" not in x}
            if types and left_labs and right_labs:
                d = rel.direction
                for tname in types:
                    rd = _ensure_rel(tname)
                    for ls in left_labs:
                        for rs in right_labs:
                            # OUTGOING and BOTH: record left→right as start→end
                            pair = (
                                (rs, ls)
                                if d is a.Direction.INCOMING
                                else (ls, rs)
                            )
                            if pair not in rd.endpoints:
                                rd.endpoints.append(pair)
            i += 2

    def _endpoints(types: list[str]) -> tuple[set[str], set[str]]:
        starts: set[str] = set()
        ends: set[str] = set()
        for tname in types:
            rd = _rel_def(tname)
            if rd is None:
                continue
            for s, e in rd.endpoints:
                starts.add(s)
                ends.add(e)
        return starts, ends

    def _infer_path(path: a.PathPattern) -> bool:
        changed = False
        els = list(path.elements or [])
        # Stamp prior-bound labels onto bare reuse sites before schema/neighbor inference
        for el in els:
            if not isinstance(el, a.NodePattern):
                continue
            vn = _var_name(el)
            if vn and not _existing_labels(el) and vn in var_labels:
                changed |= _apply_labels(el, var_labels[vn])
        i = 0
        while i + 2 < len(els):
            left, rel, right = els[i], els[i + 1], els[i + 2]
            if not (
                isinstance(left, a.NodePattern)
                and isinstance(rel, a.RelationshipPattern)
                and isinstance(right, a.NodePattern)
            ):
                i += 1
                continue
            types = [str(t) for t in (rel.types or [])]
            if not types:
                i += 2
                continue
            starts, ends = _endpoints(types)
            left_labs = {x for x in _existing_labels(left) if "|" not in x}
            right_labs = {x for x in _existing_labels(right) if "|" not in x}

            if left_labs:
                left_l = {x.lower() for x in left_labs}
                narrowed_ends: set[str] = set()
                for tname in types:
                    rd = _rel_def(tname)
                    if rd is None:
                        continue
                    for s, e in rd.endpoints:
                        if s.lower() in left_l:
                            narrowed_ends.add(e)
                if narrowed_ends:
                    ends = narrowed_ends
            if right_labs:
                right_l = {x.lower() for x in right_labs}
                narrowed_starts: set[str] = set()
                for tname in types:
                    rd = _rel_def(tname)
                    if rd is None:
                        continue
                    for s, e in rd.endpoints:
                        if e.lower() in right_l:
                            narrowed_starts.add(s)
                if narrowed_starts:
                    starts = narrowed_starts

            d = rel.direction
            if d is a.Direction.OUTGOING:
                changed |= _apply_labels(left, starts)
                changed |= _apply_labels(right, ends)
            elif d is a.Direction.INCOMING:
                changed |= _apply_labels(left, ends)
                changed |= _apply_labels(right, starts)
            else:
                if starts == ends and len(starts) == 1:
                    changed |= _apply_labels(left, starts)
                    changed |= _apply_labels(right, ends)
                elif left_labs and not right_labs:
                    changed |= _apply_labels(right, ends if ends else starts)
                elif right_labs and not left_labs:
                    changed |= _apply_labels(left, starts if starts else ends)
                elif not left_labs and not right_labs and len(starts | ends) == 1:
                    one = starts | ends
                    changed |= _apply_labels(left, one)
                    changed |= _apply_labels(right, one)

            # No neighbor-label copy fallback: inventing the other end's label from
            # the adjacent node greenwashes heterogeneous edges (e.g. Software-
            # [:CREATED_BY]->(b) → (b:Software)). Prefer CG1402 unless schema /
            # mined endpoints can infer a real label.
            i += 2
        return changed

    paths: list[a.PathPattern] = []
    for match in tree.find_all(a.Match):
        assert isinstance(match, a.Match)
        if not isinstance(match.pattern, a.Pattern):
            continue
        for path in match.pattern.paths or []:
            if isinstance(path, a.PathPattern):
                paths.append(path)
                for el in path.elements or []:
                    if isinstance(el, a.NodePattern):
                        labs = {x for x in _existing_labels(el) if "|" not in x}
                        vn = _var_name(el)
                        if vn and labs:
                            var_labels.setdefault(vn, set()).update(labs)

    for path in paths:
        _mine_path(path)

    for _ in range(8):
        changed = False
        for path in paths:
            changed |= _infer_path(path)
        if changed:
            for path in paths:
                _mine_path(path)
        else:
            break
    return tree
