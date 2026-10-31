"""What each AI provider offers, kept free of heavy imports.

The app, database and core read provider names, default models, model choices
and efforts from here instead of repeating them.
"""

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
    # Claude CLI built-in tools make the skills in claude_skills/ available.
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
            claude_skills=True,
        ),
    )
}
DEFAULT_PROVIDER = "claude"
ALL_EFFORTS = tuple(dict.fromkeys(value for _, value in CLAUDE_EFFORTS))


def provider_info(name: str) -> ProviderInfo:
    info = PROVIDERS.get(name.strip().casefold())
    if info is None:
        raise ValueError(
            "AI provider ต้องเป็น " + ", ".join(PROVIDERS)
        )
    return info
