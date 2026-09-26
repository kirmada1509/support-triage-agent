"""One replaceable, typed model call for single-call graph stages."""

from pydantic_ai import Agent

from app.models_config import LIMITS, pydantic_ai_model, role


async def call(role_name: str, output_type: type, prompt: str):
    agent = Agent(pydantic_ai_model(role_name), output_type=output_type)
    result = await agent.run(prompt, usage_limits=LIMITS[role_name])
    return result.output, result.response.model_name or role(role_name).primary.key
