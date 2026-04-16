"""
Pretty logging for the generation pipeline.
Box-drawing characters for clean, readable terminal output.
"""

W = 56  # Inner width of boxes


def header(title: str):
    """Section header with top border."""
    print(f"\n┌{'─' * W}┐")
    print(f"│{f'  {title}':<{W}}│")
    print(f"├{'─' * W}┤")


def row(key: str, value, max_val=42):
    """Key-value row. Value is auto-truncated."""
    val_str = str(value)
    if len(val_str) > max_val:
        val_str = val_str[:max_val - 3] + "..."
    line = f"  {key:<10} {val_str}"
    if len(line) > W:
        line = line[:W - 3] + "..."
    print(f"│{line:<{W}}│")


def row_full(key: str, value):
    """Key-value row that wraps long values on multiple lines (never truncated)."""
    val_str = str(value)
    prefix = f"  {key:<10} "
    max_content = W - len(prefix)
    if max_content < 10:
        max_content = W - 4
    # First line
    first_chunk = val_str[:max_content]
    line = f"{prefix}{first_chunk}"
    print(f"│{line:<{W}}│")
    # Continuation lines
    remaining = val_str[max_content:]
    indent = " " * (len(prefix))
    while remaining:
        chunk = remaining[:W - len(indent)]
        line = f"{indent}{chunk}"
        print(f"│{line:<{W}}│")
        remaining = remaining[W - len(indent):]


def row2(key1: str, val1, key2: str, val2):
    """Two key-value pairs on one row."""
    part1 = f"{key1}: {val1}"
    part2 = f"{key2}: {val2}"
    line = f"  {part1}   {part2}"
    if len(line) > W:
        line = line[:W - 3] + "..."
    print(f"│{line:<{W}}│")


def text(msg: str):
    """Free-form text row."""
    if len(msg) > W - 2:
        msg = msg[:W - 5] + "..."
    print(f"│  {msg:<{W - 2}}│")


def sep():
    """Separator line inside a box."""
    print(f"├{'─' * W}┤")


def footer():
    """Bottom border."""
    print(f"└{'─' * W}┘")


def big(title: str):
    """Big double-line header for major sections."""
    print(f"\n╔{'═' * W}╗")
    print(f"║{f'  {title}':<{W}}║")
    print(f"╚{'═' * W}╝")
