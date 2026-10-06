"""Every collection the backend opens is either erased with an account or excused
with a written reason (`account_delete.NOT_ERASED`).

The deletion list is written out by hand on purpose, which is also how a new store's
rows came to outlive the account they belonged to (the voice-learning clips, the
stopped replies). The collections are read from the code, every `db[...]`,
`db.<name>`, `scoped(db, ...)` and GridFS bucket, so a new one fails here until
somebody decides about it.
"""
import ast
import pathlib

from app.features import account_delete as ad

APP = pathlib.Path(__file__).resolve().parents[1] / "cloud" / "app"


def _module_strings():
    """NAME -> "value" for every module-level string constant, per file and by module."""
    per_file, by_module = {}, {}
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = {}
        for node in tree.body:
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            value = getattr(node, "value", None)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                consts.update({t.id: value.value for t in targets if isinstance(t, ast.Name)})
        per_file[path] = (tree, consts)
        by_module[path.stem] = consts
    return per_file, by_module


def _is_db(node):
    if isinstance(node, ast.Name):
        return node.id.endswith("db")
    if isinstance(node, ast.Attribute):
        return node.attr.endswith("db")
    if isinstance(node, ast.Call):
        f = node.func
        return getattr(f, "id", None) == "get_db" or getattr(f, "attr", None) == "get_db"
    if isinstance(node, ast.IfExp):
        return _is_db(node.body)
    return False


def _name(node, consts, by_module):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return by_module.get(node.value.id, {}).get(node.attr)
    return None   # a parameter or an f-string: its callers name the collection


def collections_in_code():
    per_file, by_module = _module_strings()
    found = {}
    for path, (tree, consts) in per_file.items():
        called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Subscript) and _is_db(node.value):
                name = _name(node.slice, consts, by_module)
            elif isinstance(node, ast.Attribute) and _is_db(node.value) \
                    and id(node) not in called and not node.attr.startswith("_"):
                name = node.attr                      # mongo_db.sandy_focus.create_index
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "scoped" \
                    and len(node.args) >= 2:
                name = _name(node.args[1], consts, by_module)
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "GridFS":
                for kw in node.keywords:
                    if kw.arg == "collection":
                        bucket = _name(kw.value, consts, by_module)
                        name = bucket and f"{bucket}.files"
            if name:
                found.setdefault(name, set()).add(str(path.relative_to(APP)))
    return found


def test_the_reader_sees_the_stores():
    found = collections_in_code()
    for known in ("sandy_entries", "sandy_stm", "conversations", "turn_stops",
                  "sandy_voice_enroll", "sandy_photo_files.files", "sandy_firmware"):
        assert known in found, known


def test_every_collection_is_erased_or_excused():
    found = collections_in_code()
    erased = ad.erased_collections()
    unclassified = {n: sorted(w) for n, w in found.items()
                    if n not in erased and n not in ad.NOT_ERASED}
    assert not unclassified, (
        f"collections nobody decided about on account deletion: {unclassified} — erase "
        "them in account_delete.py or add them to NOT_ERASED with the reason")
    assert not set(erased) & set(ad.NOT_ERASED)
    assert all(reason.strip() for reason in ad.NOT_ERASED.values())


def test_no_excuse_outlives_its_collection():
    stale = set(ad.NOT_ERASED) - set(collections_in_code())
    assert not stale, f"NOT_ERASED names collections nothing opens: {sorted(stale)}"
