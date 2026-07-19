import contextlib
from dataclasses import dataclass

from pydantic_ai.models import Model
from pydantic_ai.providers import Provider


@dataclass
class ModelInfo:
    """Details about a model as returned by the API."""

    model: str
    context_length: int | None = None
    input_price: float | None = None  # per million tokens
    output_price: float | None = None  # per million tokens


@dataclass
class ProviderRef:
    """Mutable holder for the current provider connection, enabling runtime replacement."""

    provider: Provider


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
        ) -> "ModelInfo | None":
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
        ) -> "ModelInfo | None":
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
