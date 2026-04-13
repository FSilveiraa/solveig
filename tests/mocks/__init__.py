from solveig import APIType, SolveigConfig

from .interface import MockInterface
from .llm_client import MockLLMClient, create_mock_client

DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    encoder="cl100k_base",
    temperature=0.0,
    verbose=False,
    min_disk_space_left="1gb",
    auto_save_session=False,
)

VERBOSE_CONFIG = DEFAULT_CONFIG.with_(verbose=True)

__all__ = [
    "DEFAULT_CONFIG",
    "VERBOSE_CONFIG",
    "MockInterface",
    "MockLLMClient",
    "create_mock_client",
]
