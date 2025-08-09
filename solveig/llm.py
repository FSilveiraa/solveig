from enum import Enum
from urllib.parse import urlunparse

import instructor


class APIType(Enum):
    OPENAI = ("https", "api.openai.com", 443, "/v1")
    CHATGPT = OPENAI
    LOCAL = ("http", "localhost", 5001, "/v1")
    CLAUDE = ("https", "api.anthropic.com", 443, "/v1")
    ANTHROPIC = CLAUDE
    GEMINI = ("https", "generativelanguage.googleapis.com", 443, "/v1beta")

    def __init__(self, scheme: str, host: str, port: int, endpoint: str):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.endpoint = endpoint

    @property
    def url(self) -> str:
        netloc = f"{self.host}:{self.port}"
        return urlunparse((self.scheme, netloc, self.endpoint, "", "", ""))


def get_instructor_client(
    api_type: APIType,
    api_key: str | None = None,
    url: str | None = None,
    skip_instructor_system_prompt=True,
) -> instructor.Instructor:
    # NoneType throws error, but we don't want to enforce having an API key for local runs
    api_key = api_key or ""

    if api_type == APIType.OPENAI or api_type == APIType.LOCAL:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=url)
            return instructor.from_openai(client, mode=instructor.Mode.JSON)
        except ImportError:
            raise ValueError("OpenAI client not available. Install with: pip install openai")
    elif api_type == APIType.CLAUDE or api_type == APIType.ANTHROPIC:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=api_key, base_url=url)
            return instructor.from_anthropic(client, mode=instructor.Mode.JSON)
        except ImportError:
            raise ValueError("Anthropic client not available. Install with: pip install anthropic")
    elif api_type == APIType.GEMINI:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            client = genai.GenerativeModel('gemini-pro')
            return instructor.from_gemini(client, mode=instructor.Mode.JSON)
        except ImportError:
            raise ValueError("Google Generative AI client not available. Install with: pip install google-generativeai")
    else:
        raise ValueError(f"Unsupported API type: {api_type}")
