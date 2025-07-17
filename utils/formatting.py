import tiktoken


YES = { "y", "yes" }
TRUNCATE_JOIN = "(...)"


def truncate_output(content: str, max_size: int) -> str:
    content_to_print = content
    if len(content) > max_size:
        size_of_each_side = int((max_size - len(TRUNCATE_JOIN)) / 2)
        content_to_print = content[:size_of_each_side] + TRUNCATE_JOIN + content[size_of_each_side:]
    return content_to_print


def ask_yes(prompt: str) -> bool:
    return input(prompt).strip().lower() in YES


def count_tokens(text: str) -> int:
    encoding = None
    try:
        encoding = tiktoken.encoding_for_model("gpt-4o").encode(text)
    except Exception as e:
        print(e)
    return len(encoding) if encoding else 0
