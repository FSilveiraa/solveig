"""Provider abstraction — APIType base class, Client, model subcommands.

`APIType` is a base class with one thin subclass per API (OpenAI, Anthropic,
Gemini).  Subclasses implement provider construction, model wrapping, and API
introspection.  `config.api.type` holds an instance.  `Client` holds the
live provider connection and subscribes to config changes reactively.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai.models import Model
from pydantic_ai.providers import Provider

from solveig.subcommands import subcommand

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface


# ---------------------------------------------------------------------------
# APIType — base class with one thin subclass per API
# ---------------------------------------------------------------------------


class APIType:
    """Base: override default_url and provider/model methods per API."""

    default_url: str = ""

    def display_value(self) -> str:
        return type(self).__name__.lower()

    def get_provider(
        self, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        raise NotImplementedError

    def get_model(self, provider: Provider, model_name: str) -> Model:
        raise NotImplementedError

    async def get_model_details(
        self, provider: Provider, model: str | None
    ) -> ModelInfo | None:
        raise NotImplementedError

    async def list_models(self, provider: Provider) -> list[str]:
        raise NotImplementedError


class OpenAI(APIType):
    default_url = "https://api.openai.com/v1"

    def get_provider(
        self, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key, base_url=url or self.default_url)

    def get_model(self, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.openai import OpenAIChatModel

        return OpenAIChatModel(model_name, provider=provider)

    async def get_model_details(
        self, provider: Provider, model_name: str | None
    ) -> ModelInfo | None:
        models_list = await provider.client.models.list()
        if model_name:
            model_obj = next((m for m in models_list.data if m.id == model_name), None)
            if model_obj is None:
                raise ModelNotFound(model_name, [m.id for m in models_list.data])
        else:
            if not models_list.data:
                return None
            model_obj = models_list.data[0]
            model_name = model_obj.id
        info = ModelInfo(model=model_name)
        with contextlib.suppress(Exception):
            info.context_length = model_obj.model_extra["context_length"]
        with contextlib.suppress(Exception):
            info.input_price = round(
                float(model_obj.model_extra["pricing"]["prompt"]) * 1_000_000, 2
            )
            info.output_price = round(
                float(model_obj.model_extra["pricing"]["completion"]) * 1_000_000, 2
            )
        return info

    async def list_models(self, provider: Provider) -> list[str]:
        models_list = await provider.client.models.list()
        return sorted(m.id for m in models_list.data)


class Anthropic(APIType):
    default_url = "https://api.anthropic.com/v1"

    def get_provider(
        self, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key, base_url=url or self.default_url)

    def get_model(self, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.anthropic import AnthropicModel

        return AnthropicModel(model_name, provider=provider)


class Gemini(APIType):
    default_url = "https://generativelanguage.googleapis.com/v1beta"

    def get_provider(
        self, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleProvider(api_key=api_key, base_url=url or None)  # type: ignore[arg-type]

    def get_model(self, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.google import GoogleModel

        return GoogleModel(model_name, provider=provider)


TYPE_BY_NAME: dict[str, type[APIType]] = {
    "openai": OpenAI,
    "anthropic": Anthropic,
    "gemini": Gemini,
}
"""String → subclass for config validation and editor choices."""


def resolve_api_type(name: str) -> APIType:
    """Build an APIType instance from a string name."""
    cls = TYPE_BY_NAME.get(name.lower())
    if cls is None:
        available = ", ".join(TYPE_BY_NAME)
        raise ValueError(f"Unknown API type: {name}. Available: {available}")
    return cls()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ModelInfo:
    """API-reported model facts."""

    model: str
    context_length: int | None = None
    input_price: float | None = None  # per million tokens
    output_price: float | None = None  # per million tokens


class ModelNotFound(Exception):
    """The requested model was not found in the provider's model list."""

    def __init__(self, model_name: str, available: list[str] | None = None) -> None:
        self.model_name = model_name
        self.available = sorted(available) if available else []


# ---------------------------------------------------------------------------
# Client — holds runtime provider, reactive to config
# ---------------------------------------------------------------------------


class Client:
    """Mutable holder for the live provider connection.  Subscribes to
    api.model / api.url / api.type changes at construction: builds a new
    provider locally and only swaps on success — the old provider stays
    live until the replacement is proven.  On failure, reverts the model
    so the UI sees the reversion."""

    def __init__(self, config: SolveigConfig, provider: Provider | None = None) -> None:
        self.provider = provider or config.api.type.get_provider(
            api_key=config.api.key.get_secret_value() or None,
            url=config.api.url,
        )
        self.type = config.api.type
        self.model_info: ModelInfo | None = None

        @config.on_change("api.model", "api.url", "api.type")
        async def _on_api_change(_config: SolveigConfig, paths: frozenset[str]):
            return await self._on_api_change(_config, paths)

    async def _on_api_change(
        self, config: SolveigConfig, paths: frozenset[str]
    ) -> None:
        if (
            self.model_info
            and self.model_info.model == config.api.model
            and self.provider.base_url == config.api.url
            and type(self.type) is type(config.api.type)
        ):
            return
        await self.refresh(config)

    async def refresh(self, config: SolveigConfig) -> None:
        """Build provider from config, fetch model details, atomic swap."""
        old_model = config.api.model
        api_type = config.api.type
        try:
            new_provider = api_type.get_provider(
                url=config.api.url,
                api_key=config.api.key.get_secret_value(),
            )
            info = await api_type.get_model_details(
                provider=new_provider, model=config.api.model
            )
        except Exception:
            await config.set("api.model", old_model)
            return

        if info is None:
            await config.set("api.model", old_model)
            return

        self.provider = new_provider
        self.type = api_type
        self.model_info = info
        # Apply the model's max context length if the user didn't specify one
        if info.context_length is not None and config.api.max_context is None:
            await config.set("api.max_context", info.context_length)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@subcommand("/model list", section="model")
async def model_list(
    config: SolveigConfig,
    client: Client,
    interface: SolveigInterface,
) -> None:
    """List available models from the provider."""
    try:
        models = await config.api.type.list_models(client.provider)
    except NotImplementedError as e:
        await interface.display_error(str(e))
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
        "\n".join(lines), title=f"Models ({type(config.api.type).__name__})"
    )


@subcommand("/model set", section="model", detail=True)
async def model_set(
    config: SolveigConfig,
    model: str,
) -> None:
    """Set the active model."""
    await config.set("api.model", model.strip())


@subcommand("/model info", section="model", detail=True)
async def model_info(
    client: Client,
    interface: SolveigInterface,
) -> None:
    """Show current model details."""
    info = client.model_info
    if info is None:
        await interface.display_info("No model info loaded. Run /model refresh.")
        return

    lines = [f"Model:           {info.model}"]
    if info.context_length is not None:
        lines.append(f"Context length:  {info.context_length:,} tokens")
    if info.input_price is not None:
        lines.append(f"Input price:    ${info.input_price:.2f}/M tokens")
    if info.output_price is not None:
        lines.append(f"Output price:   ${info.output_price:.2f}/M tokens")

    await interface.display_text_box("\n".join(lines), title="Model Info")


@subcommand("/model refresh", section="model", detail=True)
async def model_refresh(
    config: SolveigConfig,
    client: Client,
) -> None:
    """Refresh model details from the API."""
    client.model_info = None
    await client.refresh(config)
