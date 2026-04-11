"""Unit tests for the schema validation helper."""

import pytest

from app.services.schema_validation import (
    SchemaValidationError,
    validate_against_schema,
)


def test_valid_payload_passes():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
    # Should not raise
    validate_against_schema({"name": "Alice", "age": 30}, schema)


def test_missing_required_field_raises_with_field_path():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_against_schema({}, schema)
    err = exc_info.value
    assert "name" in err.message
    assert err.field == "" or err.field == "/"  # root-level error


def test_wrong_type_raises_with_field_path():
    schema = {
        "type": "object",
        "properties": {"age": {"type": "integer"}},
    }
    with pytest.raises(SchemaValidationError) as exc_info:
        validate_against_schema({"age": "thirty"}, schema)
    assert exc_info.value.field.endswith("age") or "age" in exc_info.value.message


def test_empty_schema_accepts_anything():
    validate_against_schema({"random": "data"}, {})
    validate_against_schema({}, {})


def test_none_schema_accepts_anything():
    validate_against_schema({"anything": 1}, None)


def test_enum_violation_caught():
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["a", "b", "c"]},
        },
    }
    with pytest.raises(SchemaValidationError):
        validate_against_schema({"status": "d"}, schema)
