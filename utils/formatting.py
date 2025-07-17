import tiktoken
import shutil


YES = { "y", "yes" }
TRUNCATE_JOIN = "(...)"
INPUT_PROMPT = "Reply:\n > "

terminal_width = shutil.get_terminal_size((80, 20)).columns


def truncate_output(content: str, max_size: int) -> str:
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
