from solveig import SolveigConfig, APIType
from solveig.schema import LLMMessage
from tests.utils.mocks.requirement import MockRequirementFactory

from .interface import MockInterface
from .requirement import MockRequirementFactory


DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,

    verbose=False,
)

VERBOSE_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=True,
)

ALL_REQUIREMENTS_MESSAGE = LLMMessage(
    comment="I need to read, write, run commands, move, copy, and delete files",
    requirements=MockRequirementFactory.create_all_requirements(),
)

__all__ = ["ALL_REQUIREMENTS_MESSAGE", "DEFAULT_CONFIG", "VERBOSE_CONFIG", MockInterface, MockRequirementFactory]
