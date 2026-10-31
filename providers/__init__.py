from providers.base import AIProvider
from providers.catalog import DEFAULT_EFFORT, provider_info
from providers.claude import ClaudeProvider
from providers.gemini import GeminiProvider
from providers.qwen import QwenProvider

PROVIDER_CLASSES: dict[str, type[AIProvider]] = {
    provider.name: provider
    for provider in (QwenProvider, GeminiProvider, ClaudeProvider)
}


def create_provider(
    name: str,
    model: str = "",
    effort: str = DEFAULT_EFFORT,
    api_key: str = "",
) -> AIProvider:
    info = provider_info(name)
    return PROVIDER_CLASSES[info.name](
        model=model.strip() or info.default_model,
        effort=effort.strip().casefold() or DEFAULT_EFFORT,
        api_key=api_key.strip() if info.uses_api_key else "",
    )


__all__ = ["AIProvider", "PROVIDER_CLASSES", "create_provider"]
