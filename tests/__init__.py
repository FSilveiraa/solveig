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
  @patch('scripts.solveig_cli.llm.get_instructor_client')  # Network call
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

# Shared test data for token counting tests
LOREM_IPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Morbi malesuada lacinia dignissim. Quisque in eleifend urna. Donec vel varius est. Nulla pharetra elit id pretium molestie. Sed vitae ex interdum, aliquam lectus eu, egestas justo. Praesent ut nibh nec nulla efficitur scelerisque tincidunt ut libero. Donec tempus placerat nunc non porttitor. Cras nec rutrum mauris. Nunc sed enim dignissim, laoreet eros ac, bibendum lacus. Proin eu libero vel diam luctus venenatis. Maecenas eu erat urna. Nunc id felis erat. Nam a felis nec lacus vehicula tincidunt sed non odio. Vestibulum at lacus nec erat molestie rhoncus. Suspendisse lacinia finibus arcu at varius. Aliquam feugiat pellentesque lorem, ac viverra sapien scelerisque vel.

Quisque nec volutpat sem. Integer viverra sollicitudin enim, vitae euismod sapien varius sed. Vestibulum molestie facilisis mauris, id condimentum diam lobortis eu. Praesent cursus lobortis neque eget tempus. Donec ipsum risus, laoreet nec massa ac, sollicitudin ornare ligula. Vivamus dignissim neque vitae aliquet hendrerit. Suspendisse lorem dui, interdum et tortor eget, maximus dignissim tortor. Sed in vehicula massa, vel laoreet metus. Nam nunc risus, condimentum vel eleifend quis, suscipit eu tortor. Sed at diam ultrices mauris pulvinar gravida.

Suspendisse a magna efficitur, malesuada metus at, ultrices quam. Fusce placerat est sit amet nulla finibus, ac vulputate sem gravida. Curabitur sodales dolor sem, sed sodales felis semper et. Fusce nunc nisi, pellentesque eget ex rhoncus, consectetur viverra arcu. Aenean malesuada dui nisi, in pulvinar mi condimentum eget. Lorem ipsum dolor sit amet, consectetur adipiscing elit. Nunc fermentum magna in fringilla scelerisque. Sed pellentesque est nisl, in rhoncus erat maximus vitae. Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere cubilia curae; Vestibulum eu mi nunc. Nullam eu sem suscipit, facilisis quam id, sollicitudin enim. Proin feugiat mauris ligula, quis bibendum lacus faucibus at. Nam et scelerisque dolor, sed accumsan libero.

Curabitur pretium elementum cursus. Duis eget massa ante. Proin et turpis pretium, pulvinar sapien vel, convallis lacus. Aenean sit amet nulla nec augue semper fermentum nec at ex. Integer dignissim elementum ullamcorper. Nulla sollicitudin mollis augue, bibendum condimentum est commodo et. Nulla nec nulla at ligula dignissim laoreet. Donec eleifend, felis quis sagittis bibendum, est velit vestibulum dui, nec rhoncus velit turpis in dui. Curabitur egestas nibh ac leo placerat, vitae malesuada orci tincidunt.

Mauris ut elementum est, at malesuada ante. Suspendisse gravida purus at tellus semper, a elementum est sollicitudin. Donec vestibulum ac neque sed sagittis. Duis vestibulum odio sit amet ante maximus dapibus. Suspendisse facilisis sapien non tortor blandit, sit amet ultricies metus aliquet. Quisque porttitor finibus diam id convallis. Donec tempus tellus sed turpis lobortis, non dictum sem congue. Duis vehicula justo eu rhoncus molestie. Nullam convallis metus in libero sagittis ornare. Vestibulum venenatis dignissim neque, sit amet vehicula justo elementum nec. Mauris eleifend et orci in imperdiet. Morbi ligula nibh, efficitur sed nisl eu, maximus sollicitudin ante. Praesent ac mauris nec risus ultrices auctor. Nunc tempus eros non quam porttitor ullamcorper quis eget diam. Suspendisse a lobortis ante.
""".strip()
