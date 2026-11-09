"""Golden records: which sources are trusted, and how good is a set of cited sources."""
from pathlib import Path
from urllib.parse import urlparse

import yaml

_LIST = yaml.safe_load((Path(__file__).parent / "trusted_sources.yaml").read_text())
TRUSTED = [d.lower() for d in _LIST["trusted"]]
BLOCKED = [d.lower() for d in _LIST["blocked"]]


def domain_of(url: str) -> str:
    """'https://www.WHO.int/x' -> 'who.int'"""
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    return host.removeprefix("www.")


def normalize_url(url: str) -> str:
    """Comparable URL: no scheme, www, query, fragment or trailing slash."""
    path = urlparse(url if "://" in url else "https://" + url).path
    return (domain_of(url) + path).rstrip("/").lower()


def _matches(domain: str, entry: str) -> bool:
    if entry.startswith("."):  # suffix rule, e.g. ".gov"
        return domain.endswith(entry)
    return domain == entry or domain.endswith("." + entry)  # domain + its subdomains


def is_golden(url: str) -> bool:
    domain = domain_of(url)
    if not domain or any(_matches(domain, b) for b in BLOCKED):
        return False
    return any(_matches(domain, t) for t in TRUSTED)


def _is_expected(url: str, expected: str) -> bool:
    if "/" in expected:  # URL prefix, e.g. "arxiv.org/abs/1706.03762"
        return normalize_url(url).startswith(normalize_url(expected))
    return _matches(domain_of(url), expected.lower())  # domain, e.g. "who.int"


def score_sources(urls: list[str], seen_urls: set[str], expected: list[str] | None = None) -> dict:
    """golden_precision: share of cited sources that are golden
    grounded_rate:    share the agent actually retrieved (catches invented URLs)
    expected_recall:  share of expected references found (domains like 'who.int' or URL prefixes)"""
    n = len(urls) or 1
    seen = {normalize_url(u) for u in seen_urls}
    found = [e for e in expected or [] if any(_is_expected(u, e) for u in urls)]
    return {
        "cited": len(urls),
        "golden_precision": sum(map(is_golden, urls)) / n if urls else 0.0,
        "grounded_rate": sum(normalize_url(u) in seen for u in urls) / n if urls else 0.0,
        "expected_recall": len(found) / len(expected) if expected else None,
        "expected_missing": [e for e in expected or [] if e not in found],
    }
