from __future__ import annotations

import re
from typing import Final

import phonenumbers
from phonenumbers import PhoneNumber, PhoneNumberType

# Storage/display formats
_INTERNAL_RE: Final[re.Pattern[str]] = re.compile(r"^\+82-10-\d{4}-\d{4}$$")
_DISPLAY_RE: Final[re.Pattern[str]] = re.compile(r"^010-\d{4}-\d{4}$")

# Loose cleaners to accept common user inputs
_CLEAN_REPLACE_RE: Final[re.Pattern[str]] = re.compile(r"[()\.·\s_/]+")
_DIGIT_RE: Final[re.Pattern[str]] = re.compile(r"\D+")


def _parse_kr(raw: str) -> PhoneNumber:
    if not isinstance(raw, str):
        raise ValueError("phone must be a string")
    s = raw.strip()
    if not s:
        raise ValueError("phone is empty")
    s = _CLEAN_REPLACE_RE.sub("-", s)
    try:
        # Parse with KR default region; phonenumbers handles leading '+'
        num = phonenumbers.parse(s, region="KR")
    except Exception as e:  # noqa: BLE001
        raise ValueError("invalid phone") from e
    return num


def _is_010_mobile(num: PhoneNumber) -> bool:
    # Must be a valid KR number and MOBILE (or mixed) and start with 010 (nationally)
    if not phonenumbers.is_valid_number(num):
        return False
    if num.country_code != 82:
        return False
    ntype = phonenumbers.number_type(num)
    if ntype not in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE):
        return False
    national = str(num.national_number)
    # Enforce 010 only, 10 digits total ("10" + 8 digits)
    return len(national) == 10 and national.startswith("10")


def is_valid_kr(v: str) -> bool:
    try:
        num = _parse_kr(v)
    except ValueError:
        return False
    return _is_010_mobile(num)


def normalize_kr(v: str) -> str:
    """
    Normalize arbitrary KR mobile input to storage format: +82-10-####-####.
    Only 010 mobiles are accepted.
    """
    num = _parse_kr(v)
    if not _is_010_mobile(num):
        raise ValueError("unsupported phone (KR 010 only)")
    national = f"{num.national_number:010d}"  # 10 digits, ensure zero-padding-safe
    last8 = national[2:]  # skip '10'
    return f"+82-10-{last8[:4]}-{last8[4:]}"


def display_kr(internal: str) -> str:
    """
    Convert storage format to display format: 010-####-####.
    Accepts only the internal canonical format; otherwise raises.
    """
    if not _INTERNAL_RE.fullmatch(internal or ""):
        raise ValueError("not a canonical internal KR phone")
    # Transform "+82-10-1234-5678" -> "010-1234-5678"
    return "0" + internal[4:]  # replace '+82' with leading '0'


def mask_kr(internal_or_display: str) -> str:
    """
    Mask middle 4 digits. Always returns display format '010-****-1234'.
    Accepts either internal '+82-10-####-####' or display '010-####-####' inputs.
    """
    s = (internal_or_display or "").strip()
    if _INTERNAL_RE.fullmatch(s):
        disp = display_kr(s)
    elif _DISPLAY_RE.fullmatch(s):
        disp = s
    else:
        # Try last resort parse & normalize
        disp = display_kr(normalize_kr(s))
    # Mask middle block
    head, tail = disp.split("-")[0], disp[-4:]
    return f"{head}-****-{tail}"


__all__ = ["normalize_kr", "is_valid_kr", "display_kr", "mask_kr"]
