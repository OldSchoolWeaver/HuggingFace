"""Thin wrapper around smolagents' built-in Gradio UI that adds a title, description and examples.

The old course template re-implemented the UI against smolagents 1.13 internals; using the maintained
UI keeps message parsing/streaming compatible when smolagents is upgraded.
"""
from smolagents import GradioUI as _SmolagentsGradioUI
from smolagents.agents import MultiStepAgent


class GradioUI(_SmolagentsGradioUI):
    def __init__(
        self,
        agent: MultiStepAgent,
        title: str = "Agent",
        description: str | None = None,
        examples: list[str] | None = None,
        reset_agent_memory: bool = False,  # keep memory so follow-ups ("swap Tuesday") edit the same plan
    ):
        super().__init__(agent, reset_agent_memory=reset_agent_memory)
        self.title = title
        self.description = description
        self.examples = examples or None

    def create_app(self):
        import gradio as gr

        # Gradio 5.x needs type="messages"; Gradio 6 removed the parameter
        type_messages = {"type": "messages"} if gr.__version__.startswith("5") else {}
        chatbot = gr.Chatbot(label="Agent", height=620, **type_messages)
        return gr.ChatInterface(
            fn=self._stream_response,
            chatbot=chatbot,
            title=self.title,
            description=self.description,
            examples=self.examples,
            save_history=True,
            **type_messages,
        )

    def launch(self, share: bool = False, **kwargs):
        self.create_app().launch(share=share, **kwargs)
