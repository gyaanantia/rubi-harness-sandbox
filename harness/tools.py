from typing import Annotated, Any, Literal
from uuid import UUID

from langchain.tools import ToolRuntime
from pydantic import WithJsonSchema

from harness.registry import tool_def
from seed.crm import SECTIONS

SectionName = Annotated[str, WithJsonSchema({"type": "string", "enum": SECTIONS})]


@tool_def("read_document")
async def read_document(document_id: UUID, runtime: ToolRuntime[dict]) -> str:
    """Read a seeded CIM or teaser by document UUID."""
    ctx = runtime.context
    return ctx["gateway"].read_document(ctx["run"].firm_id, str(document_id))


@tool_def("get_deal_info")
async def get_deal_info(
    deal_id: UUID, sections: list[SectionName], runtime: ToolRuntime[dict]
) -> Any:
    """Read deal sections: overview, financials, contacts, documents, crm, screening.

    An invalid section returns an error string naming valid sections.
    """
    ctx = runtime.context
    return ctx["gateway"].get_deal_info(ctx["run"].firm_id, str(deal_id), sections)


@tool_def("list_deal_contacts")
async def list_deal_contacts(deal_id: UUID, runtime: ToolRuntime[dict]) -> list[dict]:
    """List the deal's bankers and intermediary contact ids."""
    ctx = runtime.context
    return ctx["gateway"].list_deal_contacts(ctx["run"].firm_id, str(deal_id))


@tool_def("list_crm_fields")
async def list_crm_fields(entity: str, runtime: ToolRuntime[dict]) -> dict:
    """List field definitions for entity=deal, including single-select constraints."""
    return runtime.context["gateway"].list_crm_fields(entity)


@tool_def("write_crm_field", confirmation_required=True)
async def write_crm_field(
    deal_id: UUID, field: str, value: Any, runtime: ToolRuntime[dict]
) -> dict:
    """Write one validated CRM field after approval. Never pass multiple source contacts."""
    ctx = runtime.context
    return ctx["gateway"].write_crm_field(ctx["run"].firm_id, str(deal_id), field, value)


@tool_def("set_deal_status", confirmation_required=True)
async def set_deal_status(
    deal_id: UUID,
    status: Literal["open", "qualified", "hold", "kill", "decline"],
    runtime: ToolRuntime[dict],
) -> dict:
    """Move a deal to the approved status."""
    ctx = runtime.context
    return ctx["gateway"].set_deal_status(ctx["run"].firm_id, str(deal_id), status)
