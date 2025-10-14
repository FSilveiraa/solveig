from typing import Any

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
                    except Exception as e:
                        available = set(tiktoken.list_encoding_names())
                        available.update(tiktoken.model.MODEL_TO_ENCODING.keys())
                        e.add_note(
                            f"Could not find an encoding for '{encoder_or_model}', use one of {available}"
                        )
                        raise e
                cls._encoder_cache[encoder_or_model] = encoder
            return len(encoder.encode(text))

        # @classmethod
        # def _get_encoder(cls, encoder_name: str) -> Any:
        #     raise NotImplementedError()
        #
        # @classmethod
        # def _encoder_count(cls, encoder, text):
        #     raise NotImplementedError()

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
        def _get_encoder(cls, encoder_name: str) -> Any:
            try:
                return tiktoken.encoding_for_model(encoder_name)
            except KeyError:
                try:
                    return tiktoken.get_encoding(encoder_name)
                except ValueError as e:
                    available = set(tiktoken.list_encoding_names())
                    available.update(tiktoken.model.MODEL_TO_ENCODING.keys())
                    e.add_note(
                        f"Could not find an encoding for '{encoder_name}', use one of {available}"
                    )
                    raise e

        # def _encoder_count(self, encoder, text):
        #     return encoder.count_tokens(text)

        @classmethod
        def get_client(
            cls,
            instructor_mode: instructor.Mode,
            url: str | None = default_url,
            api_key: str | None = None,
            model: str | None = None,
        ) -> instructor.Instructor:
            try:
                client = openai.AsyncOpenAI(
                    api_key=api_key, base_url=url or cls.default_url
                )
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
