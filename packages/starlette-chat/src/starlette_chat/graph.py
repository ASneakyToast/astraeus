"""
LangGraph StateGraph for the starlette-chat agent loop.

Defines a standard ReAct graph:

    START → llm → should_continue ──► tools → llm → ...
                        │
                        └──► END

``build_graph(model, tools)`` compiles and returns the graph.
``ChatState`` is the state schema shared across nodes.

Usage::

    from starlette_chat.graph import build_graph, ChatState
    from starlette_chat.tools import make_tools

    tools = make_tools(dispatcher, context)
    graph = build_graph(provider.get_model(), tools)

    async for event in graph.astream_events(initial_state, version="v2"):
        ...
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict


class ChatState(TypedDict):
    """State passed between nodes in the chat graph.

    :param messages: Full message history for this turn, including the
        system prompt (as a ``SystemMessage``), prior history, and the
        new user message. ``add_messages`` reducer appends on each update.
    :param session_id: CMS chat session document ID.
    :param context: Session context forwarded from the WebSocket client —
        contains ``doc_id``, ``version``, ``draft_body``, ``selection``, etc.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    context: dict[str, Any]


def build_graph(model: Any, tools: list) -> Any:
    """Compile and return a ReAct StateGraph.

    :param model: A LangChain ``BaseChatModel`` instance (e.g. ``ChatAnthropic``
        or ``ChatOpenAI``).
    :param tools: List of LangChain ``BaseTool`` instances from
        :func:`~starlette_chat.tools.make_tools`.
    :returns: A compiled LangGraph graph ready for ``.astream_events()``.
    """
    tool_node = ToolNode(tools)
    bound_model = model.bind_tools(tools)

    async def call_model(state: ChatState) -> dict[str, Any]:
        response = await bound_model.ainvoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: ChatState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph: StateGraph = StateGraph(ChatState)
    graph.set_entry_point("llm")
    graph.add_node("llm", call_model)
    graph.add_node("tools", tool_node)
    graph.add_conditional_edges("llm", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "llm")

    return graph.compile()


def build_initial_state(
    system_prompt: str,
    history: list[dict[str, Any]],
    user_content: str,
    session_id: str,
    context: dict[str, Any],
) -> ChatState:
    """Build the initial :class:`ChatState` for a conversation turn.

    Converts raw CMS message dicts into LangChain message objects, prepends
    the system prompt, and appends the new user message.

    :param system_prompt: System prompt text (empty string if none configured).
    :param history: Prior turn messages as ``[{"role": ..., "content": ...}]`` dicts.
    :param user_content: The new user message text for this turn.
    :param session_id: CMS chat session document ID.
    :param context: Session context dict from the WebSocket client.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    messages: list[AnyMessage] = []

    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))

    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))

    messages.append(HumanMessage(content=user_content))

    return ChatState(
        messages=messages,
        session_id=session_id,
        context=context,
    )
