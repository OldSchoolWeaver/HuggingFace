"""Personal data masking: email addresses never reach the model, the stored conversation or the user.

The system prompt already tells the agent not to show emails, but a prompt isn't a guarantee. This is:

  email_masking()   LangChain's PIIMiddleware, redacting emails
                      - in tool results, before the model reads them (so it can't repeat them)
                      - in the model's answers, before they're saved or returned
  redact(text)      the same rule as a plain function, for text the app shows before the middleware has run
                    (DataAgent.stream uses it on tool results and answers)

Both use EMAIL_PATTERN, so they always agree. Redacted emails read "[REDACTED_EMAIL]".
"""

import re

from langchain.agents.middleware import PIIMiddleware

EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
_EMAIL = re.compile(EMAIL_PATTERN)
REDACTED = "[REDACTED_EMAIL]"


def redact(text: str) -> str:
    """"Write to ana.silva@voltway.pt" -> "Write to [REDACTED_EMAIL]"."""
    return _EMAIL.sub(REDACTED, text) if isinstance(text, str) else text


def email_masking() -> PIIMiddleware:
    """The user's own question is left alone (apply_to_input=False): masking it would only confuse the model."""
    return PIIMiddleware("email", strategy="redact", detector=EMAIL_PATTERN,
                         apply_to_input=False, apply_to_tool_results=True, apply_to_output=True)
