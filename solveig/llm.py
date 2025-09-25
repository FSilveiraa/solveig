# from enum import Enum
from typing import Any

# from urllib.parse import urlparse, urlunparse
import instructor
import openai
import tiktoken


class APIType:
    class BaseAPI:
        # keep a cache of encoders instantiated for each model used
        _encoder_cache: dict[str | None, Any] = {
            None: tiktoken.get_encoding("cl100k_base")
        }
        default_url = ""
        name = ""

        @classmethod
        def count_tokens(cls, text: str, encoder: str | None = None) -> int:
            try:
                actual_encoder = cls._encoder_cache[encoder]
            except KeyError:
                assert encoder is not None
                try:
                    actual_encoder = cls._get_encoder(encoder)
                except Exception:
                    actual_encoder = cls._encoder_cache[None]
                cls._encoder_cache[encoder] = actual_encoder
            return len(actual_encoder.encode(text))

        @classmethod
        def _get_encoder(cls, encoder: str) -> Any:
            raise NotImplementedError()

        @staticmethod
        def get_client(
            instructor_mode: instructor.Mode,
            url: str | None = default_url,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.Instructor:
            raise NotImplementedError()

    class OPENAI(BaseAPI):
        default_url = "https://api.openai.com/v1"
        name = "openai"

        @classmethod
        def _get_encoder(cls, encoder: str) -> Any:
            try:
                return tiktoken.encoding_for_model(encoder)
            except KeyError:
                try:
                    return tiktoken.get_encoding(encoder)
                except ValueError as e:
                    available = set(tiktoken.list_encoding_names())
                    available.update(tiktoken.model.MODEL_TO_ENCODING.keys())
                    e.add_note(
                        f"Could not find an encoding for '{encoder}', use one of {available}"
                    )
                    raise e

        @classmethod
        def get_client(
            cls,
            instructor_mode: instructor.Mode,
            url: str | None = default_url,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.Instructor:
            try:
                client = openai.OpenAI(api_key=api_key, base_url=url or cls.default_url)
                return instructor.from_openai(client, mode=instructor_mode)
            except ImportError as e:
                raise ValueError(
                    "OpenAI client not available. Install with: pip install openai"
                ) from e

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

        @classmethod
        def _get_encoder(cls, encoder: str | None = None) -> Any:
            # TODO: there's an official API for this, for now stick to the default one
            # https://docs.claude.com/en/docs/build-with-claude/token-counting
            return cls._encoder_cache[None]

        @classmethod
        def get_client(
            cls,
            instructor_mode: instructor.Mode,
            url: str | None = None,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.Instructor:
            try:
                import anthropic

                client = anthropic.Anthropic(
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

        @classmethod
        def _get_encoder(cls, encoder: str) -> Any:
            try:
                import google.generativeai as google_ai

                return google_ai.GenerativeModel(encoder)
            except ImportError as e:
                raise ImportError(
                    "Install Google Generative AI support: pip install solveig[google]"
                ) from e

        @staticmethod
        def get_client(
            instructor_mode: instructor.Mode,
            url: str | None = None,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.Instructor:
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
    instructor_mode: instructor.Mode = instructor.Mode.TOOLS,
) -> instructor.Instructor:
    """Get instructor client - backwards compatible interface."""
    # Handle legacy string API type names
    if isinstance(api_type, str):
        api_class = parse_api_type(api_type)
    else:
        api_class = api_type

    return api_class.get_client(
        url=url, api_key=api_key, model=model, instructor_mode=instructor_mode
    )
