from core.golden import is_golden, score_sources


def test_trusted_domains_subdomains_and_suffixes():
    assert is_golden("https://www.who.int/x")
    assert is_golden("https://pubmed.ncbi.nlm.nih.gov/1")  # subdomain of nih.gov
    assert is_golden("https://cs.stanford.edu/x")  # ".edu" suffix rule


def test_untrusted_blocked_and_lookalikes():
    assert not is_golden("https://medium.com/post")
    assert not is_golden("https://random-blog.example.com")
    assert not is_golden("https://who.int.evil.com/x")
    assert not is_golden("not a url")


def test_score_sources():
    s = score_sources(["https://www.who.int/a", "https://medium.com/b"], seen_urls={"https://who.int/a"},
                      expected=["who.int", "cdc.gov", "arxiv.org/abs/1706.03762"])
    assert s["golden_precision"] == 0.5 and s["grounded_rate"] == 0.5
    assert s["expected_missing"] == ["cdc.gov", "arxiv.org/abs/1706.03762"]
    assert not score_sources(["https://who.integrity.com/x"], set(), ["who.int"])["expected_recall"]
