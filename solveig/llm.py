import contextlib
from dataclasses import dataclass
from typing import Any

import instructor
import openai
import tiktoken
from instructor import AsyncInstructor


@dataclass
class ModelInfo:
    """Details about a model as returned by the API."""

    model: str
    context_length: int | None = None
    input_price: float | None = None  # per million tokens
    output_price: float | None = None  # per million tokens


@dataclass
class ClientRef:
    """Mutable holder for AsyncInstructor, enabling runtime client replacement."""

    client: AsyncInstructor


class APIType:
    class BaseAPI:
        # keep a cache of encoders instantiated for each model used
        _encoder_cache: dict[str | None, Any] = {
            None: tiktoken.get_encoding("cl100k_base")
        }
        default_url = ""
        name = ""

        @classmethod
        def count_tokens(
            cls, text: str | dict, encoder_or_model: str | None = None
        ) -> int:
            # account for openai-format message
            if isinstance(text, dict):
                text = text.get("content", "") + text.get("role", "")

            try:
                encoder = cls._encoder_cache[encoder_or_model]
            except KeyError:
                assert encoder_or_model is not None
                try:
                    encoder = tiktoken.encoding_for_model(encoder_or_model)
                except (KeyError, ValueError):
                    try:
                        encoder = tiktoken.get_encoding(encoder_or_model)
                    except Exception:
                        # available = set(tiktoken.list_encoding_names())
                        # available.update(tiktoken.model.MODEL_TO_ENCODING.keys())
                        # e.add_note(
                        #     f"Could not find an encoding for '{encoder_or_model}', use one of {available}"
                        # )
                        # raise e
                        encoder = cls._encoder_cache[None]
                cls._encoder_cache[encoder_or_model] = encoder
            return len(encoder.encode(text))

        @staticmethod
        def get_client(
            instructor_mode: instructor.Mode,
            url: str | None = default_url,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.AsyncInstructor:
            raise NotImplementedError()

        @staticmethod
        async def get_model_details(
            client: AsyncInstructor, model: str | None
        ) -> "ModelInfo | None":
            raise NotImplementedError()

    class OPENAI(BaseAPI):
        default_url = "https://api.openai.com/v1"
        name = "openai"

        @classmethod
        def get_client(
            cls,
            instructor_mode: instructor.Mode,
            url: str | None = default_url,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.AsyncInstructor:
            try:
                client = openai.AsyncOpenAI(
                    api_key=api_key, base_url=url or cls.default_url
                )
                return instructor.from_openai(client, mode=instructor_mode)
            except ImportError as e:
                raise ValueError(
                    "OpenAI client not available. Install with: pip install openai"
                ) from e

        @staticmethod
        async def get_model_details(
            client: AsyncInstructor, model: str | None
        ) -> "ModelInfo | None":
            assert client.client  # mypy
            models_list = await client.client.models.list()
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
            with contextlib.suppress(Exception):
                info.input_price = model_obj.model_extra["pricing"]["prompt"]
                info.output_price = model_obj.model_extra["pricing"]["completion"]
            return info

    class LOCAL(OPENAI):
        default_url = "https://localhost:5001/v1"
        name = "local"

        @classmethod
        def _find_encoder_for_model(cls, model: str) -> Any:
            assert model
            return tiktoken.encoding_for_model(model)

    class ANTHROPIC(BaseAPI):
        default_url = "https://api.anthropic.com/v1"
        name = "anthropic"

        # TODO: there's an official API for this, for now stick to the default one
        # https://docs.claude.com/en/docs/build-with-claude/token-counting
        # @classmethod
        # def _get_encoder(cls, encoder: str | None = None) -> Any:
        #      if config.use_anthropic_api:
        #          ...
        #      else:
        #          return OPENAI._get_encoder(encoder)

        @classmethod
        def get_client(
            cls,
            instructor_mode: instructor.Mode,
            url: str | None = None,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.AsyncInstructor:
            try:
                import anthropic

                client = anthropic.AsyncAnthropic(
                    api_key=api_key, base_url=url or cls.default_url
                )
                return instructor.from_anthropic(client, mode=instructor_mode)
            except ImportError as e:
                raise ImportError(
                    "Install Anthropic support: pip install solveig[anthropic]"
                ) from e

    class GEMINI(BaseAPI):
        default_url = "https://generativelanguage.googleapis.com/v1beta"
        name = "gemini"

        @staticmethod
        def get_client(
            instructor_mode: instructor.Mode,
            url: str | None = None,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.AsyncInstructor:
            try:
                import google.generativeai as google_ai

                google_ai.configure(api_key=api_key)
                gemini_client = google_ai.GenerativeModel(model or "gemini-pro")
                return instructor.from_gemini(gemini_client, mode=instructor_mode)
            except ImportError as e:
                raise ImportError(
                    "Install Google Generative AI support: pip install solveig[google]"
                ) from e


API_TYPES = {
    "OPENAI": APIType.OPENAI,
    "LOCAL": APIType.LOCAL,
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


def get_instructor_client(
    api_type: type[APIType.BaseAPI] | str,
    api_key: str | None = None,
    url: str | None = None,
    model: str | None = None,
    instructor_mode: instructor.Mode = instructor.Mode.JSON,
) -> instructor.AsyncInstructor:
    """Get instructor client - backwards compatible interface."""
    # Handle legacy string API type names
    if isinstance(api_type, str):
        api_class = parse_api_type(api_type)
    else:
        api_class = api_type

    return api_class.get_client(
        url=url, api_key=api_key, model=model, instructor_mode=instructor_mode
    )


class ModelNotFound(Exception):
    def __init__(self, model_name: str, available: list[str] | None = None) -> None:
        self.model_name = model_name
        self.available = sorted(available) if available else []

    def get_available_models_str(self):
        if not self.available:
            return None
        return "\n".join(self.available)
