"""
LangGraph StateGraph for the starlette-chat agent loop.

Defines a standard ReAct graph:

    START → llm → should_continue ──► tools → llm → ...
                        │
                        └──► END

``build_graph(model, tools, checkpointer)`` compiles and returns the graph.
``ChatState`` is the state schema shared across nodes.

Usage::

    from starlette_chat.graph import build_graph, ChatState
    from starlette_chat.tools import make_tools

    tools = make_tools(dispatcher, context)
    graph = build_graph(provider.get_model(), tools, checkpointer=checkpointer)

    config = {"configurable": {"thread_id": session_id, "system_prompt": "..."}}
    async for event in graph.astream_events({"messages": [user_msg], ...}, config, version="v2"):
        ...
"""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict


class ChatState(TypedDict):
    """State passed between nodes in the chat graph.

    :param messages: Message history for this thread. ``add_messages`` reducer
        appends on each update; the checkpointer persists across turns.
    :param session_id: CMS chat session document ID.
    :param context: Session context forwarded from the WebSocket client —
        contains ``doc_id``, ``version``, ``draft_body``, ``selection``, etc.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    session_id: str
    context: dict[str, Any]


def build_graph(model: Any, tools: list, checkpointer: Any = None) -> Any:
    """Compile and return a ReAct StateGraph.

    :param model: A LangChain ``BaseChatModel`` instance (e.g. ``ChatAnthropic``
        or ``ChatOpenAI``).
    :param tools: List of LangChain ``BaseTool`` instances from
        :func:`~starlette_chat.tools.make_tools`.
    :param checkpointer: Optional LangGraph checkpointer for persistent memory.
        Pass a ``MemorySaver`` or ``SqliteSaver`` instance. When ``None``, the
        graph is stateless (history is rebuilt from the CMS on each turn).
    :returns: A compiled LangGraph graph ready for ``.astream_events()``.
    """
    tool_node = ToolNode(tools)
    bound_model = model.bind_tools(tools)

    async def call_model(state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        # Prepend system prompt on every call so it's never persisted in the
        # checkpointed messages list (avoids accumulation across turns).
        system_prompt = (config.get("configurable") or {}).get("system_prompt", "")
        messages = state["messages"]
        if system_prompt:
            messages = [SystemMessage(content=system_prompt), *messages]
        response = await bound_model.ainvoke(messages)
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

    return graph.compile(checkpointer=checkpointer)
