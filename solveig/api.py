import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai.models import Model
from pydantic_ai.providers import Provider

from solveig.subcommands import subcommand

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface


@dataclass
class ModelInfo:
    """Details about a model as returned by the API."""

    model: str
    context_length: int | None = None
    input_price: float | None = None  # per million tokens
    output_price: float | None = None  # per million tokens


@dataclass
class ProviderRef:
    """Mutable holder for the current provider connection, enabling runtime replacement.

    Also caches `model_info` — the API-reported model facts (context length,
    pricing) fetched at startup / on `/model refresh`. It's provider state, not
    config: reported BY the API this ref connects to, never user-set, and it
    invalidates when the provider or model changes (the `api.model` post-set
    hook clears it)."""

    provider: Provider
    model_info: ModelInfo | None = None


class APIType:
    class BaseAPI:
        default_url = ""
        name = ""

        @staticmethod
        def get_provider(
            url: str | None = default_url,
            api_key: str | None = None,
        ) -> Provider:
            """Build the pydantic-ai `Provider` - it constructs its own SDK client internally from api_key/base_url."""
            raise NotImplementedError()

        @classmethod
        def get_model(cls, provider: Provider, model: str) -> Model:
            """Wrap a `Provider` (from `get_provider`) in the pydantic-ai `Model` used to drive the Agent."""
            raise NotImplementedError()

        @staticmethod
        async def get_model_details(
            provider: Provider, model: str | None
        ) -> ModelInfo | None:
            raise NotImplementedError()

        @staticmethod
        async def list_models(provider: Provider) -> list[str]:
            """Return the sorted model IDs available from this provider.
            Raises NotImplementedError for types that don't support listing."""
            raise NotImplementedError()

    class OPENAI(BaseAPI):
        default_url = "https://api.openai.com/v1"
        name = "openai"

        @classmethod
        def get_provider(
            cls,
            url: str | None = default_url,
            api_key: str | None = None,
        ) -> Provider:
            from pydantic_ai.providers.openai import OpenAIProvider

            return OpenAIProvider(api_key=api_key, base_url=url or cls.default_url)

        @classmethod
        def get_model(cls, provider: Provider, model: str) -> Model:
            from pydantic_ai.models.openai import OpenAIChatModel

            return OpenAIChatModel(model, provider=provider)

        @staticmethod
        async def get_model_details(
            provider: Provider, model: str | None
        ) -> ModelInfo | None:
            models_list = await provider.client.models.list()
            if model:
                model_obj = next((m for m in models_list.data if m.id == model), None)
                if model_obj is None:
                    raise ModelNotFound(model, [m.id for m in models_list.data])
            else:
                if not models_list.data:
                    return None
                model_obj = models_list.data[0]
                model = model_obj.id
            info = ModelInfo(model=model)
            with contextlib.suppress(Exception):
                info.context_length = model_obj.model_extra["context_length"]
            # Price per million tokens
            with contextlib.suppress(Exception):
                info.input_price = round(
                    float(model_obj.model_extra["pricing"]["prompt"]) * 1000000, 2
                )
                info.output_price = round(
                    float(model_obj.model_extra["pricing"]["completion"]) * 1000000, 2
                )
            return info

        @staticmethod
        async def list_models(provider: Provider) -> list[str]:
            models_list = await provider.client.models.list()
            return sorted(m.id for m in models_list.data)

    class ANTHROPIC(BaseAPI):
        default_url = "https://api.anthropic.com/v1"
        name = "anthropic"

        # TODO: there's an official API for this, for now stick to the default one
        # https://docs.claude.com/en/docs/build-with-claude/token-counting

        @classmethod
        def get_provider(
            cls,
            url: str | None = None,
            api_key: str | None = None,
        ) -> Provider:
            from pydantic_ai.providers.anthropic import AnthropicProvider

            return AnthropicProvider(api_key=api_key, base_url=url or cls.default_url)

        @classmethod
        def get_model(cls, provider: Provider, model: str) -> Model:
            from pydantic_ai.models.anthropic import AnthropicModel

            return AnthropicModel(model, provider=provider)

    class GEMINI(BaseAPI):
        default_url = "https://generativelanguage.googleapis.com/v1beta"
        name = "gemini"

        @classmethod
        def get_provider(
            cls,
            url: str | None = None,
            api_key: str | None = None,
        ) -> Provider:
            from pydantic_ai.providers.google import GoogleProvider

            # GoogleProvider's overloaded __init__ types api_key as `str` (not
            # `str | None`) on the no-client branch, but its actual impl falls back
            # to GOOGLE_API_KEY/GEMINI_API_KEY env vars when None - passing None
            # through is correct at runtime, just untyped for it.
            return GoogleProvider(api_key=api_key, base_url=url or None)  # type: ignore[arg-type]

        @classmethod
        def get_model(cls, provider: Provider, model: str) -> Model:
            from pydantic_ai.models.google import GoogleModel

            return GoogleModel(model, provider=provider)


API_TYPES = {
    "OPENAI": APIType.OPENAI,
    "ANTHROPIC": APIType.ANTHROPIC,
    "GEMINI": APIType.GEMINI,
}


def parse_api_type(api_type_str: str) -> type[APIType.BaseAPI]:
    """Convert string API type name to class."""
    api_name = api_type_str.upper()
    if api_name not in API_TYPES:
        available = ", ".join(API_TYPES.keys())
        raise ValueError(f"Unknown API type: {api_name}. Available: {available}")
    return API_TYPES[api_name]


def get_provider(
    api_type: type[APIType.BaseAPI] | str,
    api_key: str | None = None,
    url: str | None = None,
) -> Provider:
    """Build the pydantic-ai `Provider` for the given API type."""
    if isinstance(api_type, str):
        api_type = parse_api_type(api_type)
    return api_type.get_provider(url=url, api_key=api_key)


def get_model(
    api_type: type[APIType.BaseAPI] | str,
    provider: Provider,
    model: str,
) -> Model:
    """Wrap a `Provider` in the pydantic-ai `Model` used to drive the Agent."""
    if isinstance(api_type, str):
        api_type = parse_api_type(api_type)
    return api_type.get_model(provider, model)


class ModelNotFound(Exception):
    def __init__(self, model_name: str, available: list[str] | None = None) -> None:
        self.model_name = model_name
        self.available = sorted(available) if available else []

    async def print(self, interface):
        await interface.display_error(
            f"Could not find model '{self.model_name}'. Try setting with '/model set <modelname>'"
        )
        if self.available:
            await interface.display_text_box(
                text="\n".join(self.available),
                title="Available models",
                collapsed=True,
            )


# ---------------------------------------------------------------------------
# Subcommands — declared here because ProviderRef + APIType own model
# management.  SolveigConfig / SolveigInterface are TYPE_CHECKING-only
# (config.models imports APIType from here, so top-level imports would cycle);
# fetch_and_apply_model_info is imported lazily inside model_refresh.
# ---------------------------------------------------------------------------


@subcommand("/model list", section="model")
async def model_list(
    config: "SolveigConfig",
    provider_ref: ProviderRef,
    interface: "SolveigInterface",
) -> None:
    """List available models from the provider."""
    try:
        models = await config.api.type.list_models(provider_ref.provider)
    except NotImplementedError:
        await interface.display_error(
            f"Model listing is not supported for {config.api.type.name}. "
            f"Use /model set <name> to set a model manually."
        )
        return
    except Exception as e:
        await interface.display_error(f"Could not list models: {e}")
        return

    if not models:
        await interface.display_info("No models available.")
        return

    current = config.api.model
    lines = []
    for m in models:
        prefix = "→ " if m == current else "  "
        lines.append(f"{prefix}{m}")

    await interface.display_text_box(
        "\n".join(lines), title=f"Models ({config.api.type.name})"
    )


@subcommand("/model set", section="model", detail=True)
async def model_set(
    config: "SolveigConfig",
    interface: "SolveigInterface",
    model: str,
) -> None:
    """Set the active model."""
    changed = await config.change_field("api.model", model.strip())
    if changed:
        await interface.display_info(f"Model set to {model}. Fetching details...")
    else:
        await interface.display_info(f"Model already set to {model}.")


@subcommand("/model info", section="model", detail=True)
async def model_info(
    config: "SolveigConfig",
    provider_ref: ProviderRef,
    interface: "SolveigInterface",
) -> None:
    """Show current model details."""
    info = provider_ref.model_info
    if info is None:
        await interface.display_info("No model info loaded. Run /model refresh.")
        return

    lines = [
        f"Model:           {info.model}",
    ]
    if info.context_length is not None:
        lines.append(f"Context length:  {info.context_length:,} tokens")
    if info.input_price is not None:
        lines.append(f"Input price:    ${info.input_price:.2f}/M tokens")
    if info.output_price is not None:
        lines.append(f"Output price:   ${info.output_price:.2f}/M tokens")

    await interface.display_text_box("\n".join(lines), title="Model Info")


@subcommand("/model refresh", section="model", detail=True)
async def model_refresh(
    config: "SolveigConfig",
    provider_ref: ProviderRef,
    interface: "SolveigInterface",
) -> None:
    """Refresh model details from the API."""
    # Lazy import to avoid cycle: config.runtime_effects imports ModelInfo from here.
    from solveig.config.runtime_effects import fetch_and_apply_model_info

    provider_ref.model_info = None
    ok = await fetch_and_apply_model_info(config, provider_ref, interface)
    if ok:
        await interface.display_success("Model info refreshed.")
