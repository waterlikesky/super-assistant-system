"""ChannelEvent JSON Schema 校验。"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator, ValidationError

__all__ = ["ValidationError", "load_schema", "validate_event"]


@lru_cache(maxsize=1)
def load_schema() -> dict:
    text = resources.files("sas").joinpath("schemas/channel_event.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


def validate_event(event: dict) -> None:
    _validator().validate(event)
