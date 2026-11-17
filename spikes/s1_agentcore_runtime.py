"""AgentCore Runtime handler for the synthetic Cognito and Gateway spike."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2  # type: ignore[import-not-found]
from bedrock_agentcore.runtime import BedrockAgentCoreApp  # type: ignore[import-not-found]
from mcp.client.streamable_http import streamable_http_client  # type: ignore[import-not-found]
from strands import Agent  # type: ignore[import-not-found]
from strands.models import BedrockModel  # type: ignore[import-not-found]
from strands.tools.mcp import MCPClient  # type: ignore[import-not-found]

app = BedrockAgentCoreApp()


@app.entrypoint  # type: ignore[untyped-decorator]
def invoke(payload: dict[str, Any], context: Any) -> dict[str, str]:
    authorization = {
        str(key).lower(): str(value) for key, value in context.request_headers.items()
    }.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise ValueError("A forwarded Cognito access token is required.")

    @asynccontextmanager
    async def transport() -> AsyncIterator[Any]:
        async with (
            httpx2.AsyncClient(headers={"Authorization": authorization}) as http,
            streamable_http_client(
                os.environ["AGENTCORE_GATEWAY_URL"], http_client=http
            ) as streams,
        ):
            yield streams

    client = MCPClient(transport)
    with client:
        tools = client.list_tools_sync()
        expected = os.environ["VERIMED_SPIKE_TOOL_NAME"]
        tool = next(item for item in tools if item.tool_name == expected)
        agent = Agent(
            model=BedrockModel(
                model_id=os.environ["MODEL_CHALLENGER_ID"], max_tokens=128
            ),
            tools=[tool],
            callback_handler=None,
        )
        agent(f"Call the {expected} tool once. {str(payload.get('prompt', ''))[:200]}")
        for message in agent.messages:
            for block in message.get("content", []):
                result = block.get("toolResult")
                if result and result.get("status") == "success":
                    for part in result.get("content", []):
                        greeting = part.get("json")
                        if greeting is None and "text" in part:
                            try:
                                greeting = json.loads(part["text"])
                            except json.JSONDecodeError:
                                continue
                        if (
                            isinstance(greeting, dict)
                            and greeting.get("greeting") == "hello-from-verimed-gateway"
                        ):
                            return {"gateway_tool_result": greeting["greeting"]}
    raise RuntimeError("The agent did not successfully call the Gateway tool.")


if __name__ == "__main__":
    app.run()
