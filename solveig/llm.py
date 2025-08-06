from enum import Enum
from urllib.parse import urlunparse

import instructor
from openai import OpenAI


class APIType(Enum):
    OPENAI = ("https", "api.openai.com", 443, "/v1")
    CHATGPT = OPENAI
    KOBOLDCPP = ("http", "localhost", 5001, "/v1")
    CLAUDE = ("https", "api.anthropic.com", 434, "/v1")
    ANTHROPIC = CLAUDE

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

    if api_type == APIType.OPENAI:
        client = OpenAI(api_key=api_key, base_url=url)
        return instructor.from_openai(client, mode=instructor.Mode.JSON)
    elif api_type == APIType.KOBOLDCPP:
        client = OpenAI(api_key=api_key, base_url=url)  # same OpenAI-compatible API
        return instructor.from_openai(client, mode=instructor.Mode.JSON)
    # elif api_type == APIType.CLAUDE:
    #     from claude import ClaudeClient
    #     client = ClaudeClient(api_key=api_key, base_url=base_url)
    #     return instructor.from_claude(client, mode=instructor.Mode.JSON)  # hypothetical
    # elif api_type == APIType.GEMINI:
    #     from gemini import GeminiClient
    #     client = GeminiClient(api_key=api_key, base_url=base_url)
    #     return instructor.from_gemini(client, mode=instructor.Mode.JSON)  # hypothetical
    else:
        raise ValueError("Unsupported API type")
