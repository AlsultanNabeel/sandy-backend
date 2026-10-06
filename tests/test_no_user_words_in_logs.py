"""What a customer says or asks never goes to the server log (or any log drain).

A log line may say how long something was, which device and which action, never the
words: a user's sentence, the model repeating it, a search they typed. Checked on the
call itself: no argument of a logger call may read one of the names that carry words.
"""
import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "cloud" / "app"

# file -> the names that hold the user's words there
WORDS = {
    "api/voice_ws/session.py": {"user_text", "sandy_text", "t"},
}


def _logger_calls(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            yield node


def _reads(node, names):
    """A name read as itself or through a slice/attribute; `len(x)` is only a size."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
        return False
    if isinstance(node, ast.Name):
        return node.id in names
    return any(_reads(child, names) for child in ast.iter_child_nodes(node))


def test_no_log_line_carries_the_users_words():
    leaks = []
    for rel, names in WORDS.items():
        tree = ast.parse((APP / rel).read_text(encoding="utf-8"))
        for call in _logger_calls(tree):
            for arg in list(call.args) + [k.value for k in call.keywords]:
                if _reads(arg, names):
                    leaks.append(f"{rel}:{call.lineno}")
    assert not leaks, f"user words in a log line: {leaks}"
