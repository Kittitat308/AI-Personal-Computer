import asyncio
import json
from pathlib import Path
from typing import Any

from providers.base import AIProvider, ToolCallback


WORKER_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tool", "finish"]},
        "tool_name": {"type": "string"},
        "arguments": {"type": "object"},
        "status": {
            "type": "string",
            "enum": ["completed", "needs_input", "failed"],
        },
        "response": {"type": "string"},
    },
    "required": ["action"],
}


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, model: str, effort: str = "medium", api_key: str = "") -> None:
        if not api_key.strip():
            raise RuntimeError("ยังไม่ได้ตั้งค่า Gemini API key")
        super().__init__(model, effort, api_key.strip())
        try:
            from google import genai
        except ImportError as error:
            raise RuntimeError("ยังไม่ได้ติดตั้ง google-genai") from error
        self.client = genai.Client(api_key=self.api_key)
        self.pending_worker: dict[str, Any] | None = None

    def _json(self, system: str, contents: str, schema: dict[str, Any]) -> dict[str, Any]:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        return json.loads(response.text)

    async def generate_chat(self, messages, schema):
        system = messages[0]["content"]
        conversation = "\n\n".join(
            f"{item['role'].upper()}: {item['content']}" for item in messages[1:]
        )
        return await asyncio.to_thread(self._json, system, conversation, schema)

    async def execute_worker(
        self, *, task, system_prompt, skill_instructions, definitions, tools,
        call_tool: ToolCallback, registry, allowed_directories: list[Path],
    ):
        if self.pending_worker is not None:
            raise RuntimeError("Worker is already waiting for user input")
        tools_by_name = {tool.name: tool for tool in tools}
        if not tools_by_name:
            raise RuntimeError("Gemini Worker ไม่มี Tool สำหรับ Skill ที่เลือก")
        catalog = json.dumps(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
                for tool in tools
            ],
            ensure_ascii=False,
        )
        transcript = (
            f"Delegated task:\n{task.model_dump_json()}\n\n"
            f"Selected skill instructions:\n{skill_instructions}\n\n"
            f"Available tools:\n{catalog}\n\n"
            "Return JSON with action=tool, tool_name and arguments to use a tool. "
            "Return action=finish, status and response only after a tool result "
            "confirms the outcome. Use status needs_input with one short question "
            "in response when required information is missing. Use an exact "
            "available tool name."
        )
        return await self._run_worker(
            {
                "system_prompt": system_prompt,
                "transcript": transcript,
                "tools_by_name": tools_by_name,
                "call_tool": call_tool,
                "used_tool": False,
            }
        )

    async def _run_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        tools_by_name = state["tools_by_name"]
        for _ in range(6):
            action = await asyncio.to_thread(
                self._json,
                state["system_prompt"],
                state["transcript"],
                WORKER_ACTION_SCHEMA,
            )
            if action.get("action") == "finish":
                status = action.get("status") or "completed"
                if status == "needs_input":
                    state["transcript"] += (
                        "\n\nAssistant question:\n" + (action.get("response") or "")
                    )
                    self.pending_worker = state
                elif not state["used_tool"]:
                    raise RuntimeError("Worker did not call a required tool")
                return {
                    "status": status,
                    "response": action.get("response") or "ดำเนินการเสร็จแล้วครับ",
                }
            tool_name = action.get("tool_name")
            tool = tools_by_name.get(tool_name)
            if tool is None:
                state["transcript"] += (
                    f"\n\nInvalid tool name: {tool_name!r}. Choose exactly one "
                    f"from {json.dumps(list(tools_by_name))}."
                )
                continue
            output = await state["call_tool"](tool, action.get("arguments") or {})
            state["used_tool"] = True
            state["transcript"] += (
                f"\n\nTool result from {tool.name}:\n"
                + json.dumps(output, ensure_ascii=False)
            )
        raise RuntimeError("Gemini Worker exceeded the tool-call limit")

    @property
    def worker_awaiting_input(self) -> bool:
        return self.pending_worker is not None

    async def continue_worker(self, user_message: str) -> dict[str, Any]:
        state = self.pending_worker
        if state is None:
            raise RuntimeError("Worker is not waiting for user input")
        self.pending_worker = None
        state["transcript"] += (
            "\n\nUser reply:\n" + user_message.strip()
            + "\n\nContinue the same delegated task."
        )
        return await self._run_worker(state)

    async def abort_worker(self) -> None:
        self.pending_worker = None
