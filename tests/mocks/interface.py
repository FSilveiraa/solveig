from typing import Any

from solveig.interface import CLIInterface


class MockInterface(CLIInterface):
    """
    Mock interface for testing - captures all output without printing.
    Add expected outputs to list fields - user intputs, string and yes/no prompts
    Retrieve outputs (prints) in outputs field
    """

    def __init__(
        self,
    ):
        super().__init__()
        self.outputs = []
        self.user_inputs = []
        self.questions = []
        # self.yes_no_calls = []

    def _output(self, text: str) -> None:
        """Capture output instead of printing"""
        self.outputs.append(text)

    def _input(self, text: str) -> str:
        """Capture input instead of printing"""
        self.questions.append(text)
        if self.user_inputs:
            return self.user_inputs.pop(0)
        raise ValueError()

    def _output_inline(self, text: str) -> None:
        self._output(text)

    def _get_max_output_width(self) -> int:
        return 80

    def display_tree(
        self,
        metadata: dict[str, Any],
        listing: list[dict[str, Any]] | None,
        level: int | None = None,
        max_lines: int | None = None,
        title: str | None = "Metadata",
    ) -> None:
        """Mock implementation of display_tree - just captures the call."""
        tree_output = f"TREE: {title} - {metadata.get('path', 'unknown')}"
        if listing:
            tree_output += f" (with {len(listing)} entries)"
        self.outputs.append(tree_output)

    # Test helper methods
    def set_user_inputs(self, inputs: list[str]) -> None:
        """Pre-configure user inputs for testing"""
        self.user_inputs = inputs.copy()

    def get_all_output(self) -> str:
        """Get all captured output as single string"""
        return "\n".join(self.outputs)

    def assert_output_contains(self, text: str) -> None:
        """Assert that output contains specific text"""
        all_output = self.get_all_output()
        assert (
            text in all_output
        ), f"Output does not contain '{text}'. Actual output:\n{all_output}"

    def assert_output_lines_equal(self, expected_lines: list[str]) -> None:
        """Assert exact output line matching"""
        assert (
            self.outputs == expected_lines
        ), f"Output mismatch.\nExpected: {expected_lines}\nActual: {self.outputs}"

    def clear(self) -> None:
        """Clear all captured data"""
        self.outputs.clear()
        self.user_inputs.clear()
        self.questions.clear()
        self.current_level = 0
