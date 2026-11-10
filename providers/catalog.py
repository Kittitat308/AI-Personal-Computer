"""What each AI provider offers, kept free of heavy imports.

The app, database and core read provider names, default models, model choices
and efforts from here instead of repeating them.
"""

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    label: str
    default_model: str
    # (label, value) pairs; a provider without choices has a fixed model.
    models: tuple[tuple[str, str], ...] = ()
    efforts: tuple[tuple[str, str], ...] = ()
    uses_api_key: bool = False
    # Command-line program the provider needs; without it the provider is not offered.
    executable: str = ""
    # Claude CLI built-in tools make the skills in claude_skills/ available,
    # including working with files in the folder the user selects.
    claude_skills: bool = False


DEFAULT_EFFORT = "medium"
CLAUDE_EFFORTS = (
    ("Low", "low"),
    ("Medium", "medium"),
    ("High", "high"),
    ("Extra", "xhigh"),
    ("Max", "max"),
)

PROVIDERS = {
    info.name: info
    for info in (
        ProviderInfo(
            name="qwen",
            label="Qwen",
            default_model="Qwen3.5-2B-Q4_K_M.gguf",
        ),
        ProviderInfo(
            name="gemini",
            label="Gemini",
            default_model="gemini-3.5-flash-lite",
            models=(
                ("gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
                ("gemini-3.8-flash", "gemini-3.8-flash"),
            ),
            uses_api_key=True,
        ),
        ProviderInfo(
            name="claude",
            label="Claude",
            default_model="haiku",
            models=(
                ("Opus 5.5", "opus"),
                ("Sonnet 5.5", "sonnet"),
                ("Fable 5.1", "fable"),
                ("Haiku 5.5", "haiku"),
            ),
            efforts=CLAUDE_EFFORTS,
            executable="claude",
            claude_skills=True,
        ),
    )
}
DEFAULT_PROVIDER = "claude"
ALL_EFFORTS = tuple(dict.fromkeys(value for _, value in CLAUDE_EFFORTS))


def cli_available(executable: str) -> bool:
    """Whether a command-line program can be found on this computer."""
    return shutil.which(executable) is not None


def provider_available(name: str) -> bool:
    info = PROVIDERS.get(name.strip().casefold())
    return info is not None and (not info.executable or cli_available(info.executable))


def provider_info(name: str) -> ProviderInfo:
    info = PROVIDERS.get(name.strip().casefold())
    if info is None:
        raise ValueError(
            "AI provider ต้องเป็น " + ", ".join(PROVIDERS)
        )
    return info
