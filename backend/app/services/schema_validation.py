"""
Thin wrapper around jsonschema to raise a typed error we can translate
to a 422 response on public run endpoints.

Accepts None or empty-dict schemas as "no validation" (pass everything through),
which keeps legacy graphs without input_schema working.
"""

from __future__ import annotations

import jsonschema
from jsonschema import Draft202012Validator


class SchemaValidationError(ValueError):
    """Raised when a payload fails validation against a JSON Schema."""

    def __init__(self, message: str, field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def validate_against_schema(
    payload: dict,
    schema: dict | None,
) -> None:
    """
    Validate payload against schema. Raises SchemaValidationError on the first
    failure. Returns None on success. Treats None or empty schema as a pass.
    """
    if not schema:
        return

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if not errors:
        return

    first = errors[0]
    # Turn a jsonschema path like deque(['user', 'name']) into "/user/name"
    field_path = "/" + "/".join(str(p) for p in first.absolute_path)
    if field_path == "/":
        field_path = ""
    raise SchemaValidationError(
        message=f"{field_path or 'request body'}: {first.message}",
        field=field_path,
    )
