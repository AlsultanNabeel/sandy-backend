"""The model browser-use drives a fill with: ours, through `background.call("browser_step")`.

browser-use would call its provider itself; here every step goes through the one door every model
call outside a reply goes through (traced and priced on his account, under any cap set there),
on the deployment `SANDY_BACKGROUND_MODELS` names for «browser_step» (the chat's by default). A
step it asks as a structured answer is asked as a JSON schema and read back as its own model.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
MAX_TOKENS = 1500


class SandyLLM:
    """A `browser_use.llm.base.BaseChatModel` that answers through `background.call`."""

    _verified_api_keys = True

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.model = "sandy"

    @property
    def provider(self) -> str:
        return "sandy"

    @property
    def name(self) -> str:
        return "sandy"

    @property
    def model_name(self) -> str:
        return self.model

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        """browser-use keeps its model in a pydantic field: any object will do."""
        from pydantic_core import core_schema
        return core_schema.any_schema()

    async def ainvoke(self, messages: List[Any], output_format: Optional[Type[T]] = None, **kwargs: Any):
        from browser_use.llm.exceptions import ModelProviderError
        from browser_use.llm.openai.serializer import OpenAIMessageSerializer
        from browser_use.llm.schema import SchemaOptimizer
        from browser_use.llm.views import ChatInvokeCompletion

        from app.brain import background

        sent = OpenAIMessageSerializer.serialize_messages(messages)
        response_format = None
        if output_format is not None:
            response_format = {"type": "json_schema", "json_schema": {
                "name": "agent_output", "strict": True,
                "schema": SchemaOptimizer.create_optimized_json_schema(output_format)}}
        try:
            # In a copy of this context: the trace and the tenant go with it.
            answer = await asyncio.to_thread(
                background.call, "browser_step", sent, priority=background.DIRECT, user_id=self.user_id,
                max_tokens=MAX_TOKENS, temperature=0, response_format=response_format)
            text = answer.choices[0].message.content or ""
            completion = output_format.model_validate_json(text) if output_format is not None else text
        except (ValidationError, ValueError, RuntimeError, OSError, AttributeError, IndexError) as exc:
            raise ModelProviderError(message=f"the browser's step failed: {type(exc).__name__}",
                                     model=self.name) from exc
        return ChatInvokeCompletion(completion=completion, usage=None)
