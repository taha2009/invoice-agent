import json
import logging
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from typing_extensions import TypedDict

from app.config import settings
from app.sessions import create_store
from app.tools import add_remark, generate_invoice, get_invoice_info, record_payment

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an invoice assistant.
Collect invoice details from the user and call the generate_invoice tool once all required fields are confirmed.

Rules:
- Never invent or assume amounts. Ask if unclear.
- Never calculate totals yourself — the tool handles all arithmetic.
- Do not call the tool until every required field is confirmed.
- Keep replies short — the user is on Telegram.
- When generate_invoice succeeds, reply with exactly: "Invoice {number} for ₹{total} is ready."
- To correct or update an invoice, call generate_invoice with the invoice_number set to the number being corrected — either from the prior tool result or stated by the user. Collect any fields you don't already know. Never generate a new number for a correction.
- When the user asks about an existing invoice, use get_invoice_info to look it up before responding.
- When the user reports receiving payment for an invoice, use record_payment with the invoice number, payment date, and payment mode. The amount is derived from the invoice automatically.
- When the user wants to add a note or remark to an invoice, use add_remark with the invoice number and the remark text.
"""

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class InvoiceState(TypedDict):
    messages: Annotated[list, add_messages]
    pdf_files: list[dict]  # plain replace; reset each invocation in _agent_node


# ---------------------------------------------------------------------------
# LLM + tools
# ---------------------------------------------------------------------------

_llm = ChatGoogleGenerativeAI(
    model=settings.gemini_model,
    google_api_key=settings.gemini_api_key,
)
_tools = [generate_invoice, get_invoice_info, record_payment, add_remark]
_llm_with_tools = _llm.bind_tools(_tools)
_tool_executor = ToolNode(_tools)

# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def _agent_node(state: InvoiceState) -> Command:
    # System prompt injected at call time — never written to checkpointer state
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = _llm_with_tools.invoke(messages)
    update: dict = {"messages": [response]}
    # Reset PDF list at the start of each new user turn
    if isinstance(state["messages"][-1], HumanMessage):
        update["pdf_files"] = []
    return Command(update=update, goto="tools" if response.tool_calls else END)


def _tools_node(state: InvoiceState) -> Command:
    result = _tool_executor.invoke(state)
    pdf_files = list(state.get("pdf_files") or [])
    for msg in result["messages"]:
        if isinstance(msg, ToolMessage):
            try:
                content = (
                    json.loads(msg.content)
                    if isinstance(msg.content, str)
                    else msg.content
                )
                if isinstance(content, dict) and "pdf_path" in content:
                    pdf_files.append(
                        {
                            "pdf_path": content["pdf_path"],
                            "pdf_filename": content["pdf_filename"],
                        }
                    )
            except Exception:
                pass
    return Command(
        update={"messages": result["messages"], "pdf_files": pdf_files},
        goto="agent",
    )


_workflow = StateGraph(InvoiceState)
_workflow.add_node("agent", _agent_node)
_workflow.add_node("tools", _tools_node)
_workflow.set_entry_point("agent")

_store = create_store()
_graph = _workflow.compile(checkpointer=_store.checkpointer())

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class AgentResult:
    def __init__(self, text: str, pdf_files: list[dict]):
        self.text = text
        self.pdf_files = pdf_files


def reset_session(user_id: int) -> None:
    _store.reset(user_id)


async def run_agent(user_id: int, text: str) -> AgentResult:
    thread_id = _store.get_thread_id(user_id)
    config = {"configurable": {"thread_id": thread_id}}

    result = await _graph.ainvoke(
        {"messages": [HumanMessage(content=text)]},
        config,
    )

    content = result["messages"][-1].content
    if isinstance(content, str):
        final_text = content.strip()
    elif isinstance(content, list):
        final_text = " ".join(
            p["text"]
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ).strip()
    else:
        final_text = ""

    return AgentResult(text=final_text, pdf_files=result.get("pdf_files") or [])
