from typing import Optional
import phonenumbers

def normalize_phone(raw: str, default_region: str = "KR") -> Optional[str]:
    try:
        num = phonenumbers.parse(raw, default_region)
        if not phonenumbers.is_valid_number(num):
            return None
        return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return None