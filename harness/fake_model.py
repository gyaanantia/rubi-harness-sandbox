"""A deterministic policy over visible messages, using the real graph and tools."""

import json
import re
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def tool_call(name, **arguments):
    return {"name": name, "args": arguments, "id": str(uuid4()), "type": "tool_call"}


def question(prompt, options, **arguments):
    return tool_call("request_input", prompt=prompt, options=options, **arguments)


def choice_options(*names):
    return [{"id": name, "label": name.title()} for name in names]


class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "sandbox-scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = self.next_message(messages)
        return ChatResult(generations=[ChatGeneration(message=response)])

    def next_message(self, messages):
        system = messages[0].text
        kickoff = next(message.text for message in messages if isinstance(message, HumanMessage))
        deal_id = re.search(r"deal_id: ([\w-]+)", kickoff).group(1)
        calls = {
            call["id"]: call
            for message in messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
        }
        results = [
            (calls[message.tool_call_id], message)
            for message in messages
            if isinstance(message, ToolMessage) and message.tool_call_id in calls
        ]
        if "# Agent: CRM Hygiene" in system:
            return self.hygiene(deal_id, kickoff, results)
        if not results:
            document_id = re.search(r"document_id: ([\w-]+)", kickoff).group(1)
            return AIMessage(
                content="I will read the document and field definitions.",
                tool_calls=[
                    tool_call("read_document", document_id=document_id),
                    tool_call("list_deal_contacts", deal_id=deal_id),
                    tool_call("list_crm_fields", entity="deal"),
                ],
            )
        contacts_result = next(
            (message for call, message in results if call["name"] == "list_deal_contacts"), None
        )
        if contacts_result is None or contacts_result.status == "error":
            return AIMessage(content="Cannot read the contacts; no write was performed.")
        contacts = json.loads(contacts_result.content)
        asks = [(call, message) for call, message in results if call["name"] == "request_input"]
        banker_asks = [
            (call, message) for call, message in asks if call["args"].get("option_type") == "entity"
        ]
        is_screener = "# Agent: CIM Screener" in system
        if not banker_asks:
            questions = [self.banker_question(contacts)]
            document = next(
                message.content for call, message in results if call["name"] == "read_document"
            )
            ceiling = (
                float(re.search(r"EBITDA above \$(\d+)", system).group(1)) if is_screener else 0
            )
            ebitda = float(re.search(r"EBITDA: \$(\d+)", document).group(1))
            if is_screener and ebitda > ceiling:
                questions.append(
                    question("Hard fail: kill or override?", choice_options("kill", "override"))
                )
            return AIMessage(
                content="The document names several bankers; screening is complete.",
                tool_calls=questions,
            )
        writes = [(call, message) for call, message in results if call["name"] == "write_crm_field"]
        if writes and writes[-1][1].status == "error":
            failed_call, failed_message = writes[-1]
            if "REJECTED" in failed_message.content:
                return AIMessage(
                    content="CRM sync was rejected; I am reporting the failure without retrying."
                )
            recovery = [
                (call, message)
                for call, message in asks
                if call["args"]["prompt"] == "Sync failed: retry, exclude or map?"
            ]
            if len(recovery) < len(writes):
                return AIMessage(
                    content="CRM sync failed.",
                    tool_calls=[
                        question(
                            "Sync failed: retry, exclude or map?",
                            choice_options("retry", "exclude", "map"),
                        )
                    ],
                )
            selection = self.selected(recovery[-1][1])
            if selection == "retry":
                return AIMessage(
                    content="Retrying the approved field.",
                    tool_calls=[tool_call("write_crm_field", **failed_call["args"])],
                )
            if selection == "map":
                if len(banker_asks) <= len(recovery):
                    return AIMessage(
                        content="Select a replacement contact.",
                        tool_calls=[self.banker_question(contacts)],
                    )
                replacement = self.selected(banker_asks[-1][1])
                if replacement:
                    return AIMessage(
                        content="Writing the new mapping.",
                        tool_calls=[
                            tool_call(
                                "write_crm_field", **{**failed_call["args"], "value": replacement}
                            )
                        ],
                    )
            return AIMessage(content="The failed field was excluded.")
        next_calls = []
        selected = self.selected(banker_asks[-1][1])
        if not writes and selected and selected != "skip":
            next_calls.append(
                tool_call(
                    "write_crm_field",
                    deal_id=deal_id,
                    field="deal_source_individual",
                    value=selected,
                )
            )
        status_results = [message for call, message in results if call["name"] == "set_deal_status"]
        if is_screener and not status_results:
            screening = [
                message
                for call, message in asks
                if call["args"]["prompt"] == "Hard fail: kill or override?"
            ]
            decision = self.selected(screening[-1]) if screening else "qualified"
            if decision:
                status = {"override": "open", "kill": "kill"}.get(decision, "qualified")
                next_calls.append(tool_call("set_deal_status", deal_id=deal_id, status=status))
        if next_calls:
            return AIMessage(content="Applying the selected changes.", tool_calls=next_calls)
        return AIMessage(content="Finished. Skipped fields were left unchanged.")

    def selected(self, message):
        if message.status == "error":
            return None
        return json.loads(message.content).get("selected")

    def banker_question(self, contacts):
        return question(
            "Which banker should be the deal source?",
            [
                {"id": contact["id"], "label": contact["name"], "entity_id": contact["id"]}
                for contact in contacts
            ],
            option_type="entity",
        )

    def hygiene(self, deal_id, kickoff, results):
        if not results:
            return AIMessage(
                content="Checking missing fields.",
                tool_calls=[
                    tool_call(
                        "get_deal_info",
                        deal_id=deal_id,
                        sections=["overview", "crm", "screening", "contacts"],
                    ),
                    tool_call("list_crm_fields", entity="deal"),
                ],
            )
        if len(results) == 2:
            if "only deal_source_individual" in kickoff:
                return AIMessage(
                    content="An unattended ambiguous field can be skipped.",
                    tool_calls=[
                        question(
                            "Skip the ambiguous source contact?",
                            choice_options("skip"),
                            safe_default={"selected": "skip"},
                        )
                    ],
                )
            return AIMessage(
                content="Fill the missing geography.",
                tool_calls=[
                    tool_call(
                        "write_crm_field", deal_id=deal_id, field="geography", value="North America"
                    )
                ],
            )
        return AIMessage(content="Hygiene finished; skipped fields remain unset.")
