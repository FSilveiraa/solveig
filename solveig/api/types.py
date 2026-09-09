"""Provider types — `APIType` and the facts an API reports about a model.

`APIType` is a base class with one thin subclass per API (OpenAI, Anthropic,
Gemini). Subclasses implement provider construction, model wrapping, and API
introspection. `config.api.type` holds an instance.

Also home to `ApiConfig`, the `api` config section: the module that knows every
provider Solveig can talk to is the one that can say which of them a field may
hold, so `API_TYPES` is declared and consumed in one place. The only thing it
imports from solveig is the config FRAMEWORK (`ConfigSection`, `Choice`), which
imports nothing back — the section sits below config, and `client.Client`, the
live connection that uses these types, sits above it.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import override

from pydantic import Field, SecretStr, field_serializer
from pydantic_ai.models import Model
from pydantic_ai.providers import Provider

from solveig.config.models import ConfigSection, Choice


@dataclass
class ModelInfo:
    """API-reported model facts."""

    model: str
    context_length: int | None = None
    input_price: float | None = None  # per million tokens
    output_price: float | None = None  # per million tokens


class APIError(Exception):
    """A failure talking to the configured provider, classified so the UI can say
    WHICH thing is wrong rather than 'something failed'.

    The kinds are three different user actions: the endpoint can't be reached (fix
    the URL or the network), the endpoint answered and refused (fix the key or the
    account), or the endpoint answered fine and the model isn't there (fix the model
    name). A caller that only knew 'it failed' could not say any of them."""


class APIUnreachable(APIError):
    """No answer from the endpoint - bad URL, DNS failure, refused connection, timeout."""


class APIRejected(APIError):
    """The endpoint answered and refused - auth, quota, permissions."""


class ProviderCapabilityMissing(APIError):
    """This APIType doesn't implement the introspection the caller asked for.

    Not a connection failure: the provider subclass exists and can build a model, it
    simply has no model-listing support yet (see TYPE_BY_NAME's note on why such a
    provider is not offered)."""


class ModelNotFound(APIError):
    """The requested model was not found in the provider's model list."""

    def __init__(self, model_name: str, available: list[str] | None = None) -> None:
        self.model_name = model_name
        self.available = sorted(available) if available else []
        hint = f" Available: {', '.join(self.available[:10])}" if self.available else ""
        super().__init__(f"Model '{model_name}' not found at this endpoint.{hint}")


class APIType:
    """Base: override default_url, name and the provider/model methods per API."""

    name: str
    default_url: str | None = None

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not getattr(cls, "name", None):
            raise TypeError(f"{cls.__name__} must declare `name`")

    def __str__(self) -> str:
        return self.name

    @classmethod
    def get_provider(
        cls, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        raise ProviderCapabilityMissing(f"{cls.name} cannot build a provider")

    @classmethod
    def get_model(cls, provider: Provider, model_name: str) -> Model:
        raise ProviderCapabilityMissing(f"{cls.name} cannot build a model")

    @classmethod
    async def get_model_details(
        cls, provider: Provider, model: str | None
    ) -> ModelInfo | None:
        raise ProviderCapabilityMissing(f"{cls.name} cannot report model details")

    @classmethod
    async def list_models(cls, provider: Provider) -> list[str]:
        raise ProviderCapabilityMissing(f"{cls.name} cannot list models")


class OpenAI(APIType):
    name = "openai"

    @override
    @classmethod
    def get_provider(
        cls, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key, base_url=url or cls.default_url)

    @override
    @classmethod
    def get_model(cls, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.openai import OpenAIChatModel

        return OpenAIChatModel(model_name, provider=provider)

    @override
    @classmethod
    async def get_model_details(
        cls, provider: Provider, model: str | None
    ) -> ModelInfo | None:
        models_list = await provider.client.models.list()
        model_name = model
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

    @override
    @classmethod
    async def list_models(cls, provider: Provider) -> list[str]:
        models_list = await provider.client.models.list()
        return sorted(m.id for m in models_list.data)


class Anthropic(APIType):
    name = "anthropic"
    default_url = "https://api.anthropic.com/v1"

    @override
    @classmethod
    def get_provider(
        cls, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key, base_url=url or cls.default_url)

    @override
    @classmethod
    def get_model(cls, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.anthropic import AnthropicModel

        return AnthropicModel(model_name, provider=provider)


class Gemini(APIType):
    name = "gemini"
    default_url = "https://generativelanguage.googleapis.com/v1beta"

    @override
    @classmethod
    def get_provider(
        cls, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleProvider(api_key=api_key, base_url=url or None)  # type: ignore[arg-type]

    @override
    @classmethod
    def get_model(cls, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.google import GoogleModel

        return GoogleModel(model_name, provider=provider)


DEFAULT_API_TYPE = OpenAI()
# Every type of provider Solveig can talk to, keyed by its own `name`.
API_TYPES = [DEFAULT_API_TYPE]


class ApiConfig(ConfigSection):
    """API configuration"""

    url: str = Field(default="", description="LLM API endpoint URL")
    type: APIType = Choice(
        *API_TYPES,
        default=DEFAULT_API_TYPE,
        description="API provider type (openai, anthropic, gemini)",
    )

    # SecretStr so the key masks itself in repr/str/logs; the serializer un-masks
    # for /config save (secrecy is a property of the field, not of display code).
    key: SecretStr = Field(default=SecretStr(""), description="API authentication key")
    model: str | None = Field(
        default=None,
        description="LLM model identifier (e.g. gpt-4o, claude-sonnet-4-5)",
    )
    temperature: float = Field(
        default=0.0, description="Model temperature (0.0 to 2.0)"
    )
    max_context: int = Field(
        default=-1, description="Max context window in tokens (-1 = model's limit)"
    )
    timeout: float = Field(
        default=60.0, description="LLM API request timeout in seconds"
    )

    @field_serializer("key")
    def _ser_key(self, v: SecretStr) -> str:
        return v.get_secret_value()
