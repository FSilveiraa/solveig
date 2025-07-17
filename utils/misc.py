import tiktoken
import shutil


YES = { "y", "yes" }
TRUNCATE_JOIN = " (...) "
INPUT_PROMPT = "Reply:\n > "

terminal_width = shutil.get_terminal_size((80, 20)).columns


def format_output(content: str, indent=0, max_lines: int=-1, max_chars: int = 500) -> str:
    lines = content.splitlines()

    if 0 < max_lines < len(lines):
        keep_head = max_lines // 2
        keep_tail = max_lines - keep_head
        lines = lines[:keep_head] + [TRUNCATE_JOIN] + lines[-keep_tail:]

    if indent > 0:
        lines = [ (" " * indent) + line for line in lines ]
    formatted = "\n".join(lines)
    if 0 < max_chars < len(formatted):
        keep_head = max_chars // 2
        keep_tail = max_chars - keep_head
        formatted = formatted[:keep_head] + TRUNCATE_JOIN + formatted[keep_tail:]
    return formatted


# def format_output(content: str, indent=0, max_lines: int=-1, max_chars: int = 500) -> str:
#     formatted = content
#     if indent > 0:
#         formatted = "\n".join(("-" * indent) + line for line in content.splitlines())
#     # handle number of lines
#     if max_lines > 0:
#         lines = formatted.splitlines()
#         if len(lines) > max_lines:
#             keep_head = max_lines // 2
#             keep_tail = max_lines - keep_head
#             return "\n".join(
#                 lines[:keep_head] +
#                 [ TRUNCATE_JOIN ] +
#                 lines[-keep_tail:]
#             )
#     # handle number of characters
#     if 0 < max_chars < len(formatted):
#         keep_head = max_chars // 2
#         keep_tail = max_chars - keep_head
#         return formatted[:keep_head] + TRUNCATE_JOIN + formatted[keep_tail:]


def truncate_output(content: str, max_size: int, max_lines: int) -> str:
    content_to_print = content
    if len(content) > max_size:
        size_of_each_side = int((max_size - len(TRUNCATE_JOIN)) / 2)
        content_to_print = content[:size_of_each_side] + TRUNCATE_JOIN + content[size_of_each_side:]
    return content_to_print


def prompt_user(prompt: str = "Reply:\n > ") -> str:
    return input(prompt).strip()


def ask_yes(prompt: str) -> bool:
    return prompt_user(prompt).lower() in YES


def count_tokens(text: str) -> int:
    encoding = tiktoken.encoding_for_model("gpt-4o").encode(text)
    return len(encoding) if encoding else 0


def print_line(title: str = ""):
    if title:
        title = f"--- { title.strip() } "
    print(f"""\n{ title }{ "-" * (terminal_width - len(title)) }""")
