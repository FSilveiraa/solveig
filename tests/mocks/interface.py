from solveig.interface import CLIInterface


class MockInterface(CLIInterface):
    """
    Mock interface for testing - captures all output without printing.
    Add expected outputs to list fields - user intputs, string and yes/no prompts
    Retrieve outputs (prints) in outputs field
    """

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.outputs = []
        self.user_inputs = []
        self.questions = []

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

    # Test helper methods
    def set_user_inputs(self, inputs: list[str]) -> None:
        """Pre-configure user inputs for testing"""
        self.user_inputs = inputs.copy()

    def get_all_output(self) -> str:
        """Get all captured output as single string"""
        return "\n".join(self.outputs)

    def clear(self) -> None:
        """Clear all captured data"""
        self.outputs.clear()
        self.user_inputs.clear()
        self.questions.clear()
        self.current_level = 0
