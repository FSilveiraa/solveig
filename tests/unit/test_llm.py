"""
Unit tests for solveig.llm module.
Tests core token counting and API type parsing.
"""

import pytest
from solveig.llm import APIType, parse_api_type


# NOTE: tiktoken requires filesystem access for some reason
@pytest.mark.no_file_mocking
class TestTokenCounting:
    """Test core token counting functionality."""

    LOREM_IPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Morbi malesuada lacinia dignissim. Quisque in eleifend urna. Donec vel varius est. Nulla pharetra elit id pretium molestie. Sed vitae ex interdum, aliquam lectus eu, egestas justo. Praesent ut nibh nec nulla efficitur scelerisque tincidunt ut libero. Donec tempus placerat nunc non porttitor. Cras nec rutrum mauris. Nunc sed enim dignissim, laoreet eros ac, bibendum lacus. Proin eu libero vel diam luctus venenatis. Maecenas eu erat urna. Nunc id felis erat. Nam a felis nec lacus vehicula tincidunt sed non odio. Vestibulum at lacus nec erat molestie rhoncus. Suspendisse lacinia finibus arcu at varius. Aliquam feugiat pellentesque lorem, ac viverra sapien scelerisque vel.

Quisque nec volutpat sem. Integer viverra sollicitudin enim, vitae euismod sapien varius sed. Vestibulum molestie facilisis mauris, id condimentum diam lobortis eu. Praesent cursus lobortis neque eget tempus. Donec ipsum risus, laoreet nec massa ac, sollicitudin ornare ligula. Vivamus dignissim neque vitae aliquet hendrerit. Suspendisse lorem dui, interdum et tortor eget, maximus dignissim tortor. Sed in vehicula massa, vel laoreet metus. Nam nunc risus, condimentum vel eleifend quis, suscipit eu tortor. Sed at diam ultrices mauris pulvinar gravida.

Suspendisse a magna efficitur, malesuada metus at, ultrices quam. Fusce placerat est sit amet nulla finibus, ac vulputate sem gravida. Curabitur sodales dolor sem, sed sodales felis semper et. Fusce nunc nisi, pellentesque eget ex rhoncus, consectetur viverra arcu. Aenean malesuada dui nisi, in pulvinar mi condimentum eget. Lorem ipsum dolor sit amet, consectetur adipiscing elit. Nunc fermentum magna in fringilla scelerisque. Sed pellentesque est nisl, in rhoncus erat maximus vitae. Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere cubilia curae; Vestibulum eu mi nunc. Nullam eu sem suscipit, facilisis quam id, sollicitudin enim. Proin feugiat mauris ligula, quis bibendum lacus faucibus at. Nam et scelerisque dolor, sed accumsan libero.

Curabitur pretium elementum cursus. Duis eget massa ante. Proin et turpis pretium, pulvinar sapien vel, convallis lacus. Aenean sit amet nulla nec augue semper fermentum nec at ex. Integer dignissim elementum ullamcorper. Nulla sollicitudin mollis augue, bibendum condimentum est commodo et. Nulla nec nulla at ligula dignissim laoreet. Donec eleifend, felis quis sagittis bibendum, est velit vestibulum dui, nec rhoncus velit turpis in dui. Curabitur egestas nibh ac leo placerat, vitae malesuada orci tincidunt.

Mauris ut elementum est, at malesuada ante. Suspendisse gravida purus at tellus semper, a elementum est sollicitudin. Donec vestibulum ac neque sed sagittis. Duis vestibulum odio sit amet ante maximus dapibus. Suspendisse facilisis sapien non tortor blandit, sit amet ultricies metus aliquet. Quisque porttitor finibus diam id convallis. Donec tempus tellus sed turpis lobortis, non dictum sem congue. Duis vehicula justo eu rhoncus molestie. Nullam convallis metus in libero sagittis ornare. Vestibulum venenatis dignissim neque, sit amet vehicula justo elementum nec. Mauris eleifend et orci in imperdiet. Morbi ligula nibh, efficitur sed nisl eu, maximus sollicitudin ante. Praesent ac mauris nec risus ultrices auctor. Nunc tempus eros non quam porttitor ullamcorper quis eget diam. Suspendisse a lobortis ante.
""".strip()

    def test_basic_token_counting(self):
        """Test basic token counting works with strings."""
        count = APIType.OPENAI.count_tokens("hello world")
        assert isinstance(count, int)
        assert count > 0

    def test_message_format_counting(self):
        """Test counting OpenAI message format."""
        message = {"role": "user", "content": "hello"}
        count = APIType.OPENAI.count_tokens(message)
        assert isinstance(count, int)
        assert count > 0

    def test_empty_inputs(self):
        """Test empty inputs return zero."""
        assert APIType.OPENAI.count_tokens("") == 0
        assert APIType.OPENAI.count_tokens({"role": "", "content": ""}) == 0

    def test_known_token_count_cl100k_base(self):
        """Test known token count for Lorem Ipsum with cl100k_base encoder."""
        count = APIType.OPENAI.count_tokens(self.LOREM_IPSUM)
        # Known value: cl100k_base produces 1003 tokens for this text
        assert count == 1003

    def test_known_token_count_o200k_models(self):
        """Test known token count for Lorem Ipsum with o200k_base models."""
        # Test with gpt-4.1 model name and with o200k_base encoder directly
        count_model = APIType.OPENAI.count_tokens(self.LOREM_IPSUM, encoder_or_model="gpt-4.1")
        count_encoder = APIType.OPENAI.count_tokens(self.LOREM_IPSUM, "o200k_base")

        # Both should produce 763 tokens for this text
        assert count_model == 763
        assert count_encoder == 763

    def test_all_api_types_use_same_token_counting(self):
        """Test that all API types use the same BaseAPI token counting."""
        text = "hello world"

        openai_count = APIType.OPENAI.count_tokens(text)
        anthropic_count = APIType.ANTHROPIC.count_tokens(text)
        gemini_count = APIType.GEMINI.count_tokens(text)
        local_count = APIType.LOCAL.count_tokens(text)

        # All should be the same since they all use BaseAPI.count_tokens now
        assert openai_count == anthropic_count == gemini_count == local_count


class TestAPITypeParsing:
    """Test API type parsing."""

    def test_valid_api_types(self):
        """Test parsing valid API types."""
        assert parse_api_type("openai") == APIType.OPENAI
        assert parse_api_type("OPENAI") == APIType.OPENAI  # Case insensitive
        assert parse_api_type("local") == APIType.LOCAL
        assert parse_api_type("anthropic") == APIType.ANTHROPIC
        assert parse_api_type("gemini") == APIType.GEMINI

    def test_invalid_api_type(self):
        """Test invalid API type raises error."""
        with pytest.raises(ValueError, match="Unknown API type"):
            parse_api_type("invalid")

        with pytest.raises(ValueError, match="Unknown API type"):
            parse_api_type("")