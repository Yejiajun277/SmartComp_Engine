"""Carry explicitly requested public research qualifiers into later searches.

These phrases constrain discovery, never verify a source or a quoted market.
No country, brand, category or pricing templates are inferred here.
"""
import re
import unicodedata

MAX_SCOPE_PHRASES = 4
MAX_SCOPE_LENGTH = 32
_CONTACT_OR_URL = re.compile(r"@|://|www\.|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", re.I)
_PHONE = re.compile(r"(?<!\d)\+?\d[\d ().\-‐‑–—]{5,}\d(?!\d)")


def _normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _phrase(value):
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(char) in {"Cc", "Zl", "Zp"} for char in value):
        return None
    value = value.strip()
    if not 2 <= len(value) <= MAX_SCOPE_LENGTH or _CONTACT_OR_URL.search(value):
        return None
    # Preserve explicit calendar periods; they are not telephone numbers.
    phone_check = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b", "", value)
    if any(sum(char.isdigit() for char in hit.group()) >= 7 for hit in _PHONE.finditer(phone_check)):
        return None
    return value


def _pattern(phrase):
    pattern = re.escape(_normalize(phrase))
    if phrase[0].isascii() and (phrase[0].isalnum() or phrase[0] == "_"):
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if phrase[-1].isascii() and (phrase[-1].isalnum() or phrase[-1] == "_"):
        pattern += r"(?![A-Za-z0-9_])"
    return pattern


def _bounded_phrases(candidates, limit=MAX_SCOPE_PHRASES):
    if not isinstance(candidates, list):
        return []
    result, seen = [], set()
    for candidate in candidates:
        phrase = _phrase(candidate)
        if phrase and _normalize(phrase) not in seen:
            result.append(phrase)
            seen.add(_normalize(phrase))
        if limit is not None and len(result) == limit:
            break
    return result


def sanitize_scope(candidates, description, search_keywords_used, *, product_name=""):
    """Require each qualifier verbatim in the request and an actual public query."""
    if not isinstance(description, str) or not isinstance(search_keywords_used, list):
        return []
    description = _normalize(description)
    queries = [_normalize(query) for query in search_keywords_used if isinstance(query, str)]
    if isinstance(product_name, str) and product_name.strip():
        target = _pattern(product_name.strip())
        description = re.sub(target, " ", description)
        queries = [re.sub(target, " ", query) for query in queries]
    return [phrase for phrase in _bounded_phrases(candidates, limit=None)
            if re.search(_pattern(phrase), description)
            and any(re.search(_pattern(phrase), query) for query in queries)][:MAX_SCOPE_PHRASES]


def scope_queries(queries, scope):
    """Keep the existing search count and intent; add validated qualifiers only."""
    phrases = _bounded_phrases(scope)
    result = []
    for query in queries:
        missing = [phrase for phrase in phrases if not re.search(_pattern(phrase), _normalize(query))]
        result.append(" ".join([*missing, query]))
    return result
