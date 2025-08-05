"""
Test suite for Solveig.

Mocking philosophy:
  Ask yourself:
  1. "Does this thing talk to the outside world?" → Mock it
  2. "Is this thing slow or unpredictable?" → Mock it
  3. "Do I need to verify this thing was called correctly?" → Mock it
  4. "Is this just a data container or pure logic?" → Use the real thing


  Examples

   # BAD - Over-mocking
  config = Mock(spec=SolveigConfig)
  config.verbose = False

  # GOOD - Real object
  config = SolveigConfig(verbose=False, api_key="test", ...)

  # BAD - Unnecessary mock
  mock_message = Mock(spec=UserMessage)
  mock_message.comment = "Hello"

  # GOOD - Real object
  message = UserMessage(comment="Hello")

  # GOOD - Mock external dependency
  @patch('solveig.main.llm.get_instructor_client')  # Network call
  @patch('builtins.print')                          # Side effect we want to verify


  Mock the boundaries, test the logic.

  - Mock: External APIs, file system, user input, network
  - Don't mock: Your data models, pure functions, business logic


  Use `@patch` when:
  - You need the mock for most/all of the test
  - You need to inspect the mock (.assert_called_with(), etc.)
  - Multiple parts of the test need the same mock

  Use `with patch` when:
  - You only need mocking for a few lines
  - You're just setting a value, not inspecting calls
  - You want to be very explicit about what's mocked where
"""