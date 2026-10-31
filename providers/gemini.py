import asyncio
import json
from pathlib import Path
from typing import Any

from core.schemas import WorkerResult
from providers.base import AIProvider
from providers.catalog import DEFAULT_EFFORT


MAX_TOOL_ROUNDS = 6
FINAL_INSTRUCTION = (
    "Return the final Worker JSON now. Report completed only when a tool result "
    "confirms the outcome. Use needs_input with one short question when required "
    "information is missing."
)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, model: str, effort: str = DEFAULT_EFFORT, api_key: str = "") -> None:
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
        self, *, task, system_prompt, skill_instructions, definitions, registry,
        allowed_directories: list[Path],
    ):
        from google.genai import types

        if self.pending_worker is not None:
            raise RuntimeError("Worker is already waiting for user input")
        tools = await registry.list_tools(definitions)
        if not tools:
            raise RuntimeError("Gemini Worker ไม่มี Tool สำหรับ Skill ที่เลือก")
        prompt = (
            f"Delegated task:\n{task.model_dump_json()}\n\n"
            f"Selected skill instructions:\n{skill_instructions}"
        )
        return await self._run_worker(
            {
                "system_prompt": system_prompt,
                "contents": [
                    types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
                ],
                "tools_by_name": {tool.name: tool for tool in tools},
                "call_tool": registry.call_tool,
                "used_tool": False,
            }
        )

    def _generate(self, state: dict[str, Any], **options: Any):
        from google.genai import types

        return self.client.models.generate_content(
            model=self.model,
            contents=state["contents"],
            config=types.GenerateContentConfig(
                system_instruction=state["system_prompt"],
                temperature=0,
                **options,
            ),
        )

    async def _run_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        from google.genai import types

        tools_by_name = state["tools_by_name"]
        declarations = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=tool.input_schema,
                )
                for tool in tools_by_name.values()
            ]
        )
        seen_calls: set[str] = set()
        for _ in range(MAX_TOOL_ROUNDS):
            response = await asyncio.to_thread(
                self._generate,
                state,
                tools=[declarations],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            )
            calls = response.function_calls or []
            if not calls:
                break
            state["contents"].append(response.candidates[0].content)
            replies = []
            repeated = True
            for call in calls:
                arguments = dict(call.args or {})
                key = json.dumps([call.name, arguments], ensure_ascii=False, sort_keys=True)
                repeated = repeated and key in seen_calls
                seen_calls.add(key)
                tool = tools_by_name.get(call.name)
                if tool is None:
                    output = {"is_error": True, "content": f"Unknown tool: {call.name}"}
                else:
                    output = await state["call_tool"](tool, arguments)
                if not output.get("is_error"):
                    state["used_tool"] = True
                replies.append(
                    types.Part.from_function_response(
                        name=call.name, response={"result": output}
                    )
                )
            state["contents"].append(types.Content(role="user", parts=replies))
            if repeated:
                break

        state["contents"].append(
            types.Content(role="user", parts=[types.Part.from_text(text=FINAL_INSTRUCTION)])
        )
        response = await asyncio.to_thread(
            self._generate,
            state,
            response_mime_type="application/json",
            response_json_schema=WorkerResult.model_json_schema(),
        )
        result = json.loads(response.text)
        state["contents"].append(response.candidates[0].content)
        status = result.get("status")
        if status == "needs_input":
            self.pending_worker = state
        elif status == "completed" and not state["used_tool"]:
            raise RuntimeError("Worker did not complete a required tool call")
        return result

    @property
    def worker_awaiting_input(self) -> bool:
        return self.pending_worker is not None

    async def continue_worker(self, user_message: str) -> dict[str, Any]:
        from google.genai import types

        state = self.pending_worker
        if state is None:
            raise RuntimeError("Worker is not waiting for user input")
        self.pending_worker = None
        state["contents"].append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="User reply:\n" + user_message.strip()
                        + "\n\nContinue the same delegated task."
                    )
                ],
            )
        )
        return await self._run_worker(state)

    async def abort_worker(self) -> None:
        self.pending_worker = None
