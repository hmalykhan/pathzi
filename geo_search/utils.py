import re

UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)

def detect_search_kind(text: str) -> str:
    """
    Returns: 'city' | 'postcode' | 'address'
    """
    if not text:
        return "city"

    t = text.strip()
    if not t:
        return "city"

    # strong postcode signals
    compact = t.replace(" ", "")
    if UK_POSTCODE_RE.match(compact):
        return "postcode"

    has_digit = any(ch.isdigit() for ch in t)
    has_alpha = any(ch.isalpha() for ch in t)

    if has_digit and not has_alpha:
        return "postcode"      # e.g. 54000
    if has_digit and has_alpha:
        return "address"       # e.g. "12 Baker Street"
    return "city"              # letters only
