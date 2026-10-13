from pydantic import ByteSize, SecretStr

from solveig.api.types import ApiConfig, OpenAI
from solveig.config import SolveigConfig
from solveig.session.config import SessionConfig

from .client import create_mock_model
from .interface import MockInterface

DEFAULT_CONFIG = SolveigConfig(
    parse_cli=False,  # hermetic: don't parse pytest's process argv
    api=ApiConfig(
        type=OpenAI(),
        key=SecretStr("test-key"),
        url="test-url",
        model="test-model",
        temperature=0.0,
    ),
    # Normalize the disk-space check out of the way for tests. The container's
    # /tmp is a ~512MB tmpfs; the 1GB production default fires "Insufficient
    # disk space" on every file-writing tool test as a false environmental
    # failure. Individual tests that genuinely exercise the check set their own.
    minimum_disk_space_left=ByteSize(0),
    session=SessionConfig(auto_save=False),
    stream=False,
)

VERBOSE_CONFIG = DEFAULT_CONFIG

__all__ = [
    "DEFAULT_CONFIG",
    "VERBOSE_CONFIG",
    "MockInterface",
    "create_mock_model",
]
