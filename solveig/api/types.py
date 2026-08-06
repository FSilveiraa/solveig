"""Provider types — `APIType` and the facts an API reports about a model.

`APIType` is a base class with one thin subclass per API (OpenAI, Anthropic,
Gemini). Subclasses implement provider construction, model wrapping, and API
introspection. `config.api.type` holds an instance.

Imports nothing from solveig: `APIType` is a config *field type*, so it has to
sit below config. The live connection that uses these types is `client.Client`.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from pydantic_ai.models import Model
from pydantic_ai.providers import Provider


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

    default_url: str = ""
    name: str = ""

    def get_provider(
        self, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        raise ProviderCapabilityMissing(f"{self.name} cannot build a provider")

    def get_model(self, provider: Provider, model_name: str) -> Model:
        raise ProviderCapabilityMissing(f"{self.name} cannot build a model")

    async def get_model_details(
        self, provider: Provider, model: str | None
    ) -> ModelInfo | None:
        raise ProviderCapabilityMissing(f"{self.name} cannot report model details")

    async def list_models(self, provider: Provider) -> list[str]:
        raise ProviderCapabilityMissing(f"{self.name} cannot list models")


class OpenAI(APIType):
    name = "openai"
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
        self, provider: Provider, model: str | None
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

    async def list_models(self, provider: Provider) -> list[str]:
        models_list = await provider.client.models.list()
        return sorted(m.id for m in models_list.data)


class Anthropic(APIType):
    name = "anthropic"
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
    name = "gemini"
    default_url = "https://generativelanguage.googleapis.com/v1beta"

    def get_provider(
        self, url: str | None = None, api_key: str | None = None
    ) -> Provider:
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleProvider(api_key=api_key, base_url=url or None)  # type: ignore[arg-type]

    def get_model(self, provider: Provider, model_name: str) -> Model:
        from pydantic_ai.models.google import GoogleModel

        return GoogleModel(model_name, provider=provider)


#: Every provider Solveig can talk to, keyed by its own `name`.
#:
#: NOTE: Anthropic and Gemini are declared above but deliberately absent here. They
#: implement provider and model construction, but not the model introspection
#: (`get_model_details`, `list_models`) the client needs, so selecting one gives a
#: session with no model info, no price and no context limit. Re-add an entry the
#: moment its introspection lands - the name comes from the class, so that is the
#: whole change.
TYPE_BY_NAME: dict[str, type[APIType]] = {cls.name: cls for cls in (OpenAI,)}
"""String → subclass for config validation and editor choices."""


def resolve_api_type(name: str) -> APIType:
    """Build an APIType instance from a string name."""
    cls = TYPE_BY_NAME.get(name.lower())
    if cls is None:
        available = ", ".join(TYPE_BY_NAME)
        raise ValueError(f"Unknown API type: {name}. Available: {available}")
    return cls()
