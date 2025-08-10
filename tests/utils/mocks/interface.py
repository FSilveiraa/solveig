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

    def _input(self, text: str) -> None:
        """Capture input instead of printing"""
        self.questions.append(text)
        if self.user_inputs:
            return self.user_inputs.pop()
        raise ValueError()

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

    # def ask_user(self, prompt) -> str:
    #     """Mock user input - returns pre-configured responses or default"""
    #     self.prompt_calls.append(prompt)
    #     if self.user_inputs:
    #         return self.user_inputs.pop(0)
    #     raise ValueError()

    # def ask_yes_no(self, prompt: str = "") -> bool:
    #     """Mock yes/no input - returns pre-configured responses or default"""
    #     self.yes_no_calls.append(prompt)
    #     if self.user_inputs:
    #         response = self.user_inputs.pop(0)
    #         return response.lower() in DEFAULT_YES
    #     raise ValueError()

    # def display_llm_response(self, llm_response) -> None:
    #     """Mock LLM response display using context managers"""
    #     with self.section("Assistant"):
    #         if llm_response.comment:
    #             self.show(f"❝ {llm_response.comment.strip()}")
    #
    #         if llm_response.requirements:
    #             self.show("")  # Blank line
    #             with self.group("Requirements", count=len(llm_response.requirements)):
    #                 # Simple summary - individual requirement display is separate
    #                 for req in llm_response.requirements:
    #                     self.show(f"{req.title}: {req.comment}")
    #
    # def display_requirement(self, presentation: RequirementPresentation) -> None:
    #     """Mock individual requirement display using context managers"""
    #     with self.group(presentation.title):
    #         self.show(f"❝ {presentation.comment}")
    #
    #         for detail in presentation.details:
    #             self.show(detail)
    #
    #         if presentation.warnings:
    #             for warning in presentation.warnings:
    #                 self.show(warning)
    #
    #         if presentation.content_preview:
    #             with self.group("Content"):
    #                 # Simple content display without formatting
    #                 self.show(presentation.content_preview[:100] + "..." if len(
    #                     presentation.content_preview) > 100 else presentation.content_preview)

    # def display_error(self, message: str) -> None:
    #     """Mock error display"""
    #     self.show(f"ERROR: {message}")
    #
    # def display_status(self, message: str) -> None:
    #     """Mock status display"""
    #     self.show(f"STATUS: {message}")
    #
    # def display_verbose_info(self, message: str) -> None:
    #     """Mock verbose info display"""
    #     if self.be_verbose:
    #         self.show(f"VERBOSE: {message}")

    # def display_section_header(self, title: str) -> None:
    #     """Mock section header display using base class section context manager"""
    #     with self.section(title):
    #         pass  # The context manager handles the display
    #
    # def display_requirements_header(self, count: int) -> None:
    #     """Mock requirements header display"""
    #     self.show(f"[ Requirements ({count}) ]")
    #
    # def display_results_header(self, count: int) -> None:
    #     """Mock results header display"""
    #     with self.section("User"):
    #         self.show(f"[ Results ({count}) ]")

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
        # self.prompt_calls.clear()
        # self.yes_no_calls.clear()
        self.current_level = 0
