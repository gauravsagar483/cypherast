"""GraphSchema catalog checks for optimize / validate."""

from __future__ import annotations

import pytest

import cypherast
from cypherast.errors import ValidationError
from cypherast.schema import GraphSchema, PropertyDef


def _dq_schema() -> GraphSchema:
    s = GraphSchema(strict=True)
    s.add_label("DataQualityCheck", status="string", name="string")
    s.add_id_field("DataQualityCheck", "dq_check_id")
    return s


def test_schema_default_not_strict():
    assert GraphSchema().strict is False


def test_id_field_property_access_rejected_on_validate():
    schema = _dq_schema()
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck) RETURN dq.dq_check_id",
        dialect="opencypher",
        schema=schema,
    )
    assert any(i.code == "CG1305" for i in issues)
    assert any("id(dq)" in (i.hint or "") for i in issues)


def test_id_field_inline_map_rejected():
    schema = _dq_schema()
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck {dq_check_id: $x}) RETURN dq",
        schema=schema,
    )
    assert any(i.code == "CG1305" for i in issues)


def test_declared_property_ok():
    schema = _dq_schema()
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck) WHERE dq.status = 'ok' RETURN id(dq), dq.name",
        schema=schema,
    )
    assert not any(i.code in {"CG1303", "CG1305"} for i in issues)


def test_unknown_property_strict():
    schema = _dq_schema()
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck) RETURN dq.not_a_real_prop",
        schema=schema,
    )
    assert any(i.code == "CG1303" for i in issues)


def test_unknown_property_non_strict_ok():
    schema = _dq_schema()
    schema.strict = False
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck) RETURN dq.not_a_real_prop",
        schema=schema,
    )
    assert not any(i.code == "CG1303" for i in issues)
    # id field still rejected
    issues2 = cypherast.validate(
        "MATCH (dq:DataQualityCheck) RETURN dq.dq_check_id",
        schema=schema,
    )
    assert any(i.code == "CG1305" for i in issues2)


def test_no_schema_skips_property_catalog():
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck) RETURN dq.dq_check_id",
        dialect="opencypher",
    )
    assert not any(i.code in {"CG1301", "CG1302", "CG1303", "CG1305"} for i in issues)


def test_unknown_label_strict():
    schema = _dq_schema()
    issues = cypherast.validate(
        "MATCH (m:Metric) RETURN m",
        schema=schema,
    )
    assert any(i.code == "CG1301" for i in issues)


def test_unknown_label_non_strict_ok():
    schema = _dq_schema()
    schema.strict = False
    issues = cypherast.validate(
        "MATCH (m:Metric) RETURN m.metric_id",
        schema=schema,
    )
    assert not any(i.code in {"CG1301", "CG1302", "CG1303", "CG1305"} for i in issues)


def test_unknown_rel_type_strict():
    s = GraphSchema(strict=True)
    s.add_label("Person")
    s.add_rel("KNOWS", "Person", "Person")
    issues = cypherast.validate(
        "MATCH (a:Person)-[:KNOZE]->(b:Person) RETURN a",
        schema=s,
    )
    assert any(i.code == "CG1302" for i in issues)


def test_unknown_rel_type_non_strict_ok():
    s = GraphSchema(strict=False)
    s.add_label("Person")
    s.add_rel("KNOWS", "Person", "Person")
    issues = cypherast.validate(
        "MATCH (a:Person)-[:KNOZE]->(b:Person) RETURN a",
        schema=s,
    )
    assert not any(i.code == "CG1302" for i in issues)


def test_known_labels_and_rels_ok():
    s = GraphSchema(strict=True)
    s.add_label("Dataset")
    s.add_label("DimensionColumn")
    s.add_rel("INCLUDES_DIMENSION_COLUMN", "DimensionColumn", "Dataset")
    issues = cypherast.validate(
        "MATCH (dc:DimensionColumn)-[:INCLUDES_DIMENSION_COLUMN]->(ds:Dataset) "
        "RETURN ds",
        schema=s,
    )
    assert not any(i.code in {"CG1301", "CG1302"} for i in issues)


def test_optimize_raises_on_unknown_rel_type():
    s = GraphSchema(strict=True)
    s.add_label("Dataset")
    s.add_label("DimensionColumn")
    s.add_rel("INCLUDES_DIMENSION_COLUMN", "DimensionColumn", "Dataset")
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (dc:DimensionColumn)-[:INCLUDES_DIMfENSION_COLUMN]->(ds:Dataset) "
            "RETURN ds LIMIT 1",
            schema=s,
        )
    assert ei.value.code == "CG1302"


def test_label_or_half_unknown_strict():
    s = GraphSchema(strict=True)
    s.add_label("Person")
    issues = cypherast.validate(
        "MATCH (n:Person|Ghost) RETURN n",
        schema=s,
    )
    assert any(i.code == "CG1301" and "Ghost" in i.message for i in issues)


def test_rel_or_half_unknown_strict():
    s = GraphSchema(strict=True)
    s.add_label("Person")
    s.add_rel("KNOWS", "Person", "Person")
    issues = cypherast.validate(
        "MATCH (a:Person)-[:KNOWS|LIKES]->(b:Person) RETURN a",
        schema=s,
    )
    assert any(i.code == "CG1302" and "LIKES" in i.message for i in issues)


def test_remove_unknown_label_strict():
    s = GraphSchema(strict=True)
    s.add_label("Person")
    issues = cypherast.validate(
        "MATCH (n:Person) REMOVE n:Ghost RETURN n",
        schema=s,
    )
    assert any(i.code == "CG1301" and "Ghost" in i.message for i in issues)


def test_puppygraph_open_world_without_catalog():
    """No schema / non-strict → unknown labels not CG1301/CG1302."""
    issues = cypherast.validate(
        "MATCH (n:Dataset)-[:INCLUDES_DIMENSION_COLUMN]->(m:Metric) RETURN n",
        dialect="puppygraph",
    )
    assert not any(i.code in {"CG1301", "CG1302"} for i in issues)
    tree = cypherast.optimize(
        "MATCH (n:Dataset) RETURN n LIMIT 1",
        write="puppygraph",
        strict=False,
    )
    assert tree is not None


def test_optimize_raises_on_id_field():
    schema = _dq_schema()
    with pytest.raises(ValidationError) as ei:
        cypherast.optimize(
            "MATCH (dq:DataQualityCheck) RETURN dq.dq_check_id LIMIT 10",
            schema=schema,
        )
    assert ei.value.code == "CG1305"


def test_rel_id_field():
    s = GraphSchema(strict=True)
    s.add_rel("HAS_CHECK", "Person", "DataQualityCheck", weight="float")
    s.add_rel_id_field("HAS_CHECK", "edge_pk")
    issues = cypherast.validate(
        "MATCH ()-[r:HAS_CHECK]->() RETURN r.edge_pk",
        schema=s,
    )
    assert any(i.code == "CG1305" for i in issues)


def test_non_strict_ignores_undeclared_props():
    s = GraphSchema(strict=False)
    s.add_label("person")
    s.labels["person"].properties["name"] = PropertyDef(name="name", type="string")
    issues = cypherast.validate(
        "MATCH (n:person) RETURN n.extra_prop",
        schema=s,
    )
    assert not any(i.code == "CG1303" for i in issues)


def test_with_rebinding_preserves_labels():
    schema = _dq_schema()
    issues = cypherast.validate(
        "MATCH (dq:DataQualityCheck) WITH dq AS x RETURN x.dq_check_id",
        schema=schema,
    )
    assert any(i.code == "CG1305" for i in issues)
