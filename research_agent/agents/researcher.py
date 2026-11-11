"""Researcher: finds facts on the web and records only golden sources."""
import re

import requests
from aisuite import Agent
from ddgs import DDGS
from markdownify import markdownify

from core.config import model_for, run_agent, safe_tool
from core.golden import domain_of, is_golden, normalize_url
from core.state import current_run, list_sources


def _label(url: str) -> str:
    return "TRUSTED" if is_golden(url) else "NOT TRUSTED - do not cite"


@safe_tool
def web_search(query: str) -> str:
    """Search the web. Each result is labelled TRUSTED (golden source, can be cited) or NOT TRUSTED.

    Args:
        query: Search query. Restricting to a trusted site helps, e.g. "PM2.5 guidelines site:who.int".
    """
    results = DDGS().text(query, max_results=6)
    current_run().seen_urls.update(r["href"] for r in results)
    return "\n".join(f"- [{_label(r['href'])}] {r['title']}\n  {r['href']}\n  {r['body'][:300]}" for r in results) or "No results."


@safe_tool
def fetch_page(url: str) -> str:
    """Read a web page as text (first 6000 characters). Use it to get exact quotes.

    Args:
        url: URL from web_search.
    """
    html = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (research-agent)"})
    html.raise_for_status()
    current_run().seen_urls.add(url)
    text = re.sub(r"\n{3,}", "\n\n", markdownify(html.text, strip=["script", "style"]))
    return f"[{_label(url)}] {url}\n\n{text[:6000]}"


@safe_tool
def record_source(url: str, title: str, quote: str, claim: str) -> str:
    """Record a source that supports a claim. Rejected unless it is golden AND you actually retrieved it.

    Args:
        url: URL exactly as returned by web_search or fetch_page.
        title: Page or document title.
        quote: Short exact text from the source that supports the claim.
        claim: The fact this source supports, in one sentence.
    """
    run = current_run()
    if not is_golden(url):
        reason = f"{domain_of(url)} is not a golden source"
    elif normalize_url(url) not in {normalize_url(u) for u in run.seen_urls}:
        reason = "this URL never appeared in your searches or fetched pages - do not invent URLs"
    else:
        for s in run.sources:
            if normalize_url(s["url"]) == normalize_url(url):
                return f"Already recorded as [{s['id']}]."
        source_id = f"S{len(run.sources) + 1}"
        run.sources.append({"id": source_id, "url": url, "title": title, "quote": quote, "claim": claim})
        return f"Recorded as [{source_id}]. Cite it as [{source_id}]."
    if url not in (r["url"] for r in run.rejected):
        run.rejected.append({"url": url, "reason": reason})
    return f"REJECTED: {reason}. Find a trusted alternative."


INSTRUCTIONS = (
    "You are the Researcher. Answer your task using ONLY sources labelled TRUSTED.\n"
    "1. web_search (use 'site:' with trusted domains like who.int, nih.gov, arxiv.org, europa.eu).\n"
    "2. fetch_page on the best trusted results to get exact quotes.\n"
    "3. record_source(url, title, quote, claim) for EVERY fact you use. If it is rejected, find a "
    "trusted alternative. Aim for 4-8 sources.\n"
    "Reply with your findings as markdown bullets; each bullet ends with its source ids, e.g. [S1][S3]. "
    "Never state a fact without a recorded source."
)


def research_agent(task: str, model: str = model_for("researcher"), **run_options) -> str:
    """
    Researches a task on the web using only golden sources.

    Args:
        task (str): The research step, enriched with context from previous steps.
        model (str): Language model to use.

    Returns:
        str: Findings as markdown bullets citing recorded sources ([S1], [S2], ...).
    """
    agent = Agent(name="Researcher", model=model, instructions=INSTRUCTIONS,
                  tools=[web_search, fetch_page, record_source, list_sources])
    return run_agent(agent, task, turns=14, **run_options)
