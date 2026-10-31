import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

from core.config import MODELS_DIR
from core.schemas import WorkerResult
from providers.base import AIProvider
from providers.catalog import DEFAULT_EFFORT


QWEN_CONTEXT = 4096
QWEN_GPU_LAYERS = 99
LLAMA_SERVER_PATH = ""
LLAMA_SERVER_HOST = "127.0.0.1"
LLAMA_SERVER_PORT = 8080
LLAMA_DEVICE = "Vulkan1" if os.name == "nt" else "Vulkan0"


class QwenProvider(AIProvider):
    name = "qwen"
    single_instance = True

    def __init__(self, model: str, effort: str = DEFAULT_EFFORT, api_key: str = "") -> None:
        super().__init__(model, effort, api_key)
        self.model_path = MODELS_DIR / model
        if not self.model_path.is_file():
            raise FileNotFoundError(f"ไม่พบโมเดล Qwen: {self.model_path}")
        self.host = LLAMA_SERVER_HOST
        self.port = LLAMA_SERVER_PORT
        self.base_url = f"http://{self.host}:{self.port}"
        self.process: subprocess.Popen | None = None
        self._start_server_if_needed()

    @staticmethod
    def _server_candidates() -> list[Path]:
        candidates: list[Path] = []
        if LLAMA_SERVER_PATH:
            candidates.append(Path(LLAMA_SERVER_PATH).expanduser())
        executable = shutil.which("llama-server")
        if executable:
            candidates.append(Path(executable))
        if os.name == "nt":
            local_app_data = os.getenv("LOCALAPPDATA")
            if local_app_data:
                package_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
                if package_root.is_dir():
                    for directory in package_root.glob("ggml.llamacpp_*"):
                        candidates.extend(directory.rglob("llama-server.exe"))
        return candidates

    @classmethod
    def _find_server(cls) -> Path:
        for candidate in cls._server_candidates():
            if candidate.is_file():
                return candidate.resolve()
        raise FileNotFoundError(
            "ไม่พบ llama-server กรุณาติดตั้ง llama.cpp หรือกำหนด "
            "LLAMA_SERVER_PATH ใน providers/qwen.py"
        )

    def _is_ready(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/health", timeout=1.0)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            return probe.connect_ex((self.host, self.port)) == 0

    def _start_server_if_needed(self) -> None:
        if self._port_in_use():
            raise RuntimeError(f"port {self.port} ถูกใช้งานไปแล้ว")
        command = [
            str(self._find_server()),
            "-m",
            str(self.model_path),
            "--device",
            LLAMA_DEVICE,
            "-ngl",
            str(QWEN_GPU_LAYERS),
            "--ctx-size",
            str(QWEN_CONTEXT),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--reasoning",
            "off",
            "--no-webui",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.process = None
                raise RuntimeError(f"llama-server หยุดทำงานระหว่างเริ่มระบบ (code {code})")
            if self._is_ready():
                return
            time.sleep(0.25)
        self._terminate_server()
        raise TimeoutError("llama-server ใช้เวลาเริ่มระบบเกิน 180 วินาที")

    def _completion(self, **options: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 512,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        payload.update(options)
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        if not response.ok:
            raise RuntimeError(
                f"llama-server ตอบกลับผิดพลาด {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    async def generate_chat(self, messages, schema):
        result = await asyncio.to_thread(
            self._completion,
            messages=messages,
            max_tokens=320,
            response_format={"type": "json_object", "schema": schema},
        )
        return json.loads(result["choices"][0]["message"].get("content", ""))

    @staticmethod
    def _coerce(value: str, schema: dict[str, Any]) -> Any:
        value = value.strip()
        if schema.get("type") == "string":
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @classmethod
    def _xml_calls(cls, content: str, tools_by_name: dict[str, Any]) -> list[dict]:
        calls = []
        functions = re.compile(
            r"<tool_call>\s*<function=([^>]+)>(.*?)</function>\s*</tool_call>",
            re.DOTALL,
        )
        parameters = re.compile(
            r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", re.DOTALL
        )
        for index, match in enumerate(functions.finditer(content), 1):
            name = match.group(1).strip()
            tool = tools_by_name.get(name)
            if tool is None:
                raise RuntimeError(f"Worker requested unknown tool: {name}")
            properties = tool.input_schema.get("properties", {})
            arguments = {
                item.group(1).strip(): cls._coerce(
                    item.group(2), properties.get(item.group(1).strip(), {})
                )
                for item in parameters.finditer(match.group(2))
            }
            calls.append(
                {
                    "id": f"qwen-{index}",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            )
        return calls

    @staticmethod
    def _tool_payload(output: dict[str, Any]) -> Any:
        structured = output.get("structuredContent") or output.get(
            "structured_content"
        )
        if structured is not None:
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured
        for item in output.get("content", []):
            if item.get("type") != "text":
                continue
            text = item.get("text", "")
            try:
                return json.loads(text)
            except (TypeError, json.JSONDecodeError):
                return text
        return output

    async def execute_worker(
        self, *, task, system_prompt, skill_instructions, definitions, registry,
        allowed_directories: list[Path],
    ):
        tools = await registry.list_tools(definitions)
        call_tool = registry.call_tool
        if not tools:
            raise RuntimeError("Qwen Worker ไม่มี Tool สำหรับ Skill ที่เลือก")
        tools_by_name = {tool.name: tool for tool in tools}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Complete only this delegated task and use the supplied tools.\n\n"
                    f"Delegated task:\n{json.dumps(task.model_dump(), ensure_ascii=False, indent=2)}\n\n"
                    f"Selected skill instructions:\n\n{skill_instructions}"
                ),
            },
        ]
        used_tool = False
        tool_cache: dict[str, dict[str, Any]] = {}
        for _ in range(6):
            result = await asyncio.to_thread(
                self._completion,
                messages=messages,
                tools=[tool.as_openai_tool() for tool in tools],
                tool_choice="required" if not used_tool else "auto",
            )
            message = result["choices"][0]["message"]
            calls = message.get("tool_calls") or self._xml_calls(
                message.get("content") or "", tools_by_name
            )
            if not calls:
                if not used_tool:
                    raise RuntimeError("Worker did not call a required tool")
                break
            used_tool = True
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": calls,
                }
            )
            all_calls_cached = True
            for call in calls:
                function = call["function"]
                tool = tools_by_name.get(function["name"])
                if tool is None:
                    raise RuntimeError(
                        f"Worker requested unknown tool: {function['name']}"
                    )
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                cache_key = json.dumps(
                    [tool.skill_id, tool.name, arguments],
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if cache_key in tool_cache:
                    output = tool_cache[cache_key]
                else:
                    output = await call_tool(tool, arguments)
                    tool_cache[cache_key] = output
                    all_calls_cached = False
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": tool.name,
                        "content": json.dumps(
                            self._tool_payload(output), ensure_ascii=False
                        ),
                    }
                )
            if all_calls_cached:
                break
        messages.append(
            {
                "role": "user",
                "content": (
                    "Return the final Worker JSON now with status completed or "
                    "failed. Report success only when the tool result confirms it."
                ),
            }
        )
        result = await asyncio.to_thread(
            self._completion,
            messages=messages,
            response_format={
                "type": "json_object",
                "schema": self._worker_schema(),
            },
        )
        return json.loads(result["choices"][0]["message"].get("content", ""))

    @staticmethod
    def _worker_schema() -> dict[str, Any]:
        # Qwen keeps no worker session, so it cannot wait for user input.
        schema = WorkerResult.model_json_schema()
        schema["properties"]["status"]["enum"] = ["completed", "failed"]
        return schema

    def _terminate_server(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    async def close(self) -> None:
        await asyncio.to_thread(self._terminate_server)
