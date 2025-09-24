from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["normalize_phone", "is_valid_phone", "mask_phone"]


@dataclass(eq=False)
class PhoneError(Exception):
    message: str
    code: str = "ERR_INVALID_PAYLOAD"

    def __str__(self) -> str:
        return self.message


_MOBILE_PREFIX = "010"
_CC = "82"  # Korea
_INTL_RE = re.compile(r"^\+?82")
_DIGITS_RE = re.compile(r"\d+")


def _digits(s: str) -> str:
    return "".join(_DIGITS_RE.findall(s))


def _parse_to_national_10x8(s: str) -> str:
    s = s.strip()
    if not s:
        raise PhoneError("empty phone number")
    has_plus = s.startswith("+")
    d = _digits(s)

    if _INTL_RE.match(s):
        # e.g. +82 10 1234 5678 or +82 010 1234 5678
        if not d.startswith(_CC):
            raise PhoneError("invalid country code")
        rest = d[len(_CC) :]
        if rest.startswith(_MOBILE_PREFIX):
            rest = rest[1:]  # drop trunk '0' -> '10...'
        if not rest.startswith("10"):
            raise PhoneError("unsupported mobile prefix")
        if len(rest) != 10:
            raise PhoneError("invalid length for +82 number")
        return rest  # '10' + 8 digits

    # Domestic formats
    if d.startswith(_MOBILE_PREFIX):
        if len(d) != 11:
            raise PhoneError("invalid length for domestic number")
        return "1" + d[1:]  # '10' + 8 digits
    if d.startswith("10") and len(d) == 10:
        return d  # already '10' + 8 digits

    raise PhoneError("unsupported phone format")


def normalize_phone(input_str: str) -> str:
    """
    Return '+82-10-1234-5678' for valid Korean mobile numbers.
    """
    national = _parse_to_national_10x8(input_str)
    mid = national[2:6]
    last = national[6:]
    return f"+82-10-{mid}-{last}"


def is_valid_phone(input_str: str) -> bool:
    try:
        _ = normalize_phone(input_str)
        return True
    except PhoneError:
        return False


def mask_phone(input_str: str) -> str:
    """
    Return domestic masked format '010-****-1234'.
    """
    national = _parse_to_national_10x8(input_str)  # '10' + 8 digits
    mid = national[2:6]
    last = national[6:]
    return f"010-{'*'*4}-{last}"
