"""A scripted fake model and fake web search, so the whole team can be tested offline.

Each agent gets its own fake model (fake-executor, fake-planner, ...). Its script is a list of turns:
a list of tool calls, or the final text answer.
"""
import json
import os
import uuid

for name in ["executor", "planner", "researcher", "reviewer", "writer"]:
    os.environ[f"{name.upper()}_MODEL"] = f"huggingface:fake-{name}"
os.environ.setdefault("HF_TOKEN", "fake")

import aisuite as ai  # noqa: E402
import ddgs  # noqa: E402
from aisuite.framework import ChatCompletionResponse  # noqa: E402
from aisuite.framework.message import ChatCompletionMessageToolCall, Function, Message  # noqa: E402

WHO = "https://www.who.int/news-room/fact-sheets/detail/ambient-air-quality-and-health"
REPORT = f"# Air pollution and health\n\nAir pollution is a major health risk [S1].\n\n## References\n[S1] WHO - {WHO}"


def call(name, **args):
    return ChatCompletionMessageToolCall(id=uuid.uuid4().hex[:8], type="function",
                                         function=Function(name=name, arguments=json.dumps(args)))


SCRIPTS = {
    "fake-planner": ["Here is the plan:\n['Research the health effects of air pollution.', "
                     "'Review the findings and sources.', 'Write the final report.']"],
    "fake-researcher": [[call("web_search", query="air pollution site:who.int")],
                        [call("record_source", url=WHO, title="WHO", quote="major risk", claim="Air pollution is a major risk"),
                         call("record_source", url="https://medium.com/blog", title="Blog", quote="x", claim="y"),
                         call("record_source", url="https://www.nih.gov/invented", title="Fake", quote="x", claim="y")],
                        "- Air pollution is a major health risk [S1]"],
    "fake-reviewer": [[call("list_sources")], [call("check_source", url=WHO), call("submit_review", verdict="revise", feedback="Add values.")], "revise"],
    "fake-reviewer-2": [[call("submit_review", verdict="approve", feedback="Good.")], "approve"],
    "fake-writer": [[call("list_sources")], [call("save_draft", markdown=REPORT)], "Saved."],
}


class FakeModel:
    def chat_completions_create(self, model, messages, **kwargs):
        text = json.dumps(messages, default=str)
        if model == "fake-executor":  # router: pick the agent from the step's wording
            step = text.split("Step:")[-1].lower()
            agent = "editor_agent" if "review" in step else "writer_agent" if "write" in step else "research_agent"
            return _reply(json.dumps({"agent": agent, "task": step.strip(' "}]')}))
        if model == "fake-reviewer" and "- editor_agent:" in text:
            model = "fake-reviewer-2"  # a previous review is in the context -> this second review approves
        turn = sum(1 for m in messages if (m["role"] if isinstance(m, dict) else m.role) == "assistant")
        step = SCRIPTS[model][min(turn, len(SCRIPTS[model]) - 1)]
        return _reply(step)


def _reply(step):
    response = ChatCompletionResponse()
    response.choices[0].message = (Message(role="assistant", content=step) if isinstance(step, str)
                                   else Message(role="assistant", content="", tool_calls=step))
    return response


class FakeSearch:
    def text(self, query, max_results=6):
        return [{"title": "WHO fact sheet", "href": WHO, "body": "Air pollution..."},
                {"title": "A blog", "href": "https://medium.com/blog", "body": "opinions"}]


ddgs.DDGS = FakeSearch


def fake_client():
    client = ai.Client({"huggingface": {"timeout": 5}})
    client.providers["huggingface"] = FakeModel()
    return client
