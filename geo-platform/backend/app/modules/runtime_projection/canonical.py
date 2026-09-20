from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
import struct
from typing import Any


CANONICALIZATION_VERSION = "semantic_manifest_canonicalization.v1"
CANONICAL_BYTES_CONTRACT = "semantic_manifest_canonical_bytes.v1"


class CanonicalizationError(ValueError):
    pass


@dataclass(frozen=True)
class FieldState:
    code: int
    value: Any = None


FIELD_ABSENT = FieldState(0)
FIELD_PRESENT_NULL = FieldState(1)
EMPTY_COLLECTION = FieldState(2)


def value(value_: Any) -> FieldState:
    return FieldState(3, value_)


def state_for(value_: Any) -> FieldState:
    if isinstance(value_, FieldState):
        return value_
    if value_ is None:
        return FIELD_PRESENT_NULL
    if isinstance(value_, (list, tuple, dict)) and not value_:
        return EMPTY_COLLECTION
    return value(value_)


def _string(value_: str) -> bytes:
    encoded = value_.encode("utf-8")
    return b"s" + str(len(encoded)).encode("ascii") + b":" + encoded


def _decimal(value_: Decimal) -> bytes:
    if not value_.is_finite():
        raise CanonicalizationError("non-finite decimal")
    if value_.is_zero():
        rendered = "0"
    else:
        rendered = format(value_, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
    return b"d" + rendered.encode("ascii") + b";"


def _timestamp(value_: datetime) -> bytes:
    if value_.tzinfo is None:
        value_ = value_.replace(tzinfo=timezone.utc)
    utc = value_.astimezone(timezone.utc)
    rendered = utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if len(rendered.encode("ascii")) != 27:
        raise CanonicalizationError("timestamp is not UTC RFC3339 microsecond form")
    return b"t27:" + rendered.encode("ascii")


def canonical_node(value_: Any) -> bytes:
    if isinstance(value_, FieldState):
        if value_.code == 0:
            return b"x0;"
        if value_.code == 1:
            return b"x1;"
        if value_.code == 2:
            return b"x2;"
        if value_.code == 3:
            return b"x3:" + canonical_node(value_.value)
        raise CanonicalizationError(f"unknown field-state code: {value_.code}")
    if isinstance(value_, bool):
        return b"b1;" if value_ else b"b0;"
    if isinstance(value_, int):
        return b"i" + str(value_).encode("ascii") + b";"
    if isinstance(value_, Decimal):
        return _decimal(value_)
    if isinstance(value_, float):
        if not math.isfinite(value_):
            raise CanonicalizationError("non-finite float")
        if value_ == 0.0:
            value_ = 0.0
        return b"f" + struct.pack(">d", value_).hex().encode("ascii") + b";"
    if isinstance(value_, datetime):
        return _timestamp(value_)
    if isinstance(value_, str):
        return _string(value_)
    if isinstance(value_, (list, tuple)):
        members = b"".join(canonical_node(member) for member in value_)
        return b"a" + str(len(value_)).encode("ascii") + b":[" + members + b"]"
    if isinstance(value_, dict):
        keys = sorted(value_, key=lambda key: str(key).encode("utf-8"))
        if any(not isinstance(key, str) for key in keys):
            raise CanonicalizationError("object keys must be strings")
        fields = []
        for key in keys:
            fields.append(_string(key))
            fields.append(canonical_node(state_for(value_[key])))
        return (
            b"o"
            + str(len(keys)).encode("ascii")
            + b":{" + b"".join(fields) + b"}"
        )
    raise CanonicalizationError(f"unsupported canonical value: {type(value_).__name__}")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def semantic_hash(value_: Any) -> str:
    return sha256_bytes(canonical_node(value_))


def manifest_bytes(manifest_type: str, contract_version: str, payload: Any) -> bytes:
    return canonical_node(
        {
            "canonical_bytes_contract": CANONICAL_BYTES_CONTRACT,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "hash_algorithm": "SHA-256",
            "manifest_contract_version": contract_version,
            "manifest_type": manifest_type,
            "payload": payload,
        }
    )


def manifest_hash(manifest_type: str, contract_version: str, payload: Any) -> str:
    return sha256_bytes(manifest_bytes(manifest_type, contract_version, payload))
