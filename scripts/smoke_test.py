#!/usr/bin/env python3
"""Sandy backend smoke test — one command, a readable pass/fail checklist.

Runs against the LIVE server (Heroku by default) exactly like a real client:
logs in with the owner password, then exercises every major feature end-to-end
(create → read → update → delete, so it cleans up after itself) and prints a
tidy ✓/✗ list grouped by area, with a final score.

This tests the shared brain/API that ALL frontends (iOS, web, future Android)
sit on top of, so a green run here means the backbone is solid before we build
new frontends. The frontends themselves you still eyeball on-device.

Run it:
    ~/sandy_app_venv/bin/python scripts/smoke_test.py
    # or point it elsewhere / skip the prompt:
    SANDY_URL=http://nabeelsul.local:8080 SANDY_PASSWORD=xxx \
        ~/sandy_app_venv/bin/python scripts/smoke_test.py

Stdlib only — no packages needed. Read-safe: everything it creates is tagged
"[تجربة]" and deleted at the end; if a delete ever fails it says so loudly.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE_URL = (len(sys.argv) > 1 and sys.argv[1]) or os.getenv(
    "SANDY_URL", "https://sandy-robot-3da0693d32f7.herokuapp.com"
)
TAG = "[تجربة]"  # marks rows this script creates, so leftovers are obvious

# ── tiny terminal styling ────────────────────────────────────────────────
_C = sys.stdout.isatty()
def _c(code: str, s: str) -> str: return f"\033[{code}m{s}\033[0m" if _C else s
def green(s): return _c("32", s)
def red(s):   return _c("31", s)
def dim(s):   return _c("2", s)
def bold(s):  return _c("1", s)
def cyan(s):  return _c("36", s)

TOKEN = ""
_passed = 0
_failed = 0


def call(method: str, path: str, body=None, auth=True):
    """One HTTP call → (status_code, parsed_json). Never raises."""
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if auth and TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:200]}
    except Exception as e:  # noqa: BLE001
        return 0, {"_error": str(e)}


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Record + print one result line."""
    global _passed, _failed
    mark = green("✓") if ok else red("✗")
    if ok:
        _passed += 1
    else:
        _failed += 1
    line = f"  {mark} {name}"
    if detail:
        line += dim(f"   {detail}")
    print(line)
    return ok


def section(title: str):
    print("\n" + bold(cyan(f"▸ {title}")))


# ── the suite ────────────────────────────────────────────────────────────

def test_auth(password: str) -> bool:
    global TOKEN
    section("الدخول")
    st, j = call("POST", "/api/auth", {"password": password}, auth=False)
    TOKEN = j.get("token", "") if st == 200 else ""
    return check("تسجيل الدخول بكلمة السر", bool(TOKEN),
                 f"status={st}" if not TOKEN else f"user={j.get('user_id','')[:8]}…")


def test_read_only():
    section("قراءة (بلا تعديل)")
    for name, path, key in [
        ("التعارف", "/api/onboarding", None),
        ("الشخصية واللهجة", "/api/persona", "dialect"),
        ("الاشتراك", "/api/subscription", "status"),
        ("الخط الزمني", "/api/timeline", "items"),
        ("الأجهزة", "/api/devices", "items"),
    ]:
        st, j = call("GET", path)
        ok = st == 200 and (key is None or key in j)
        check(name, ok, f"status={st}")


def test_daily_nudge():
    section("التنبيه اليومي")
    st, j = call("GET", "/api/daily-nudge")
    kind = j.get("kind", "")
    check("جلب تنبيه اليوم", st == 200 and kind in ("question", "agenda", "none"),
          f"نوع={kind}")
    if kind == "question" and j.get("qid"):
        st2, _ = call("POST", "/api/daily-nudge/answer",
                      {"qid": j["qid"], "answer": f"{TAG} جواب"})
        check("إرسال جواب السؤال", st2 == 200, f"status={st2}")


def test_push():
    section("الإشعارات (توكن الجهاز)")
    tok = f"smoketest-{int(time.time())}"
    st, _ = call("POST", "/api/push/register", {"token": tok})
    check("تسجيل توكن جهاز", st == 200, f"status={st}")
    st2, _ = call("POST", "/api/push/unregister", {"token": tok})
    check("إلغاء التوكن", st2 == 200, f"status={st2}")


def _find_id(path: str, match_text: str, id_key="id", text_key="text"):
    """GET a list endpoint, return the id of the row whose text contains match."""
    st, j = call("GET", path)
    for row in (j.get("items") or []):
        if match_text in str(row.get(text_key, "")):
            return row.get(id_key)
    return None


def test_tasks():
    section("المهام (إنشاء ← إكمال ← حذف)")
    txt = f"{TAG} مهمة"
    st, j = call("POST", "/api/tasks", {"text": txt, "due": ""})
    tid = j.get("id") or _find_id("/api/tasks", txt)
    if not check("إنشاء مهمة", st == 200 and bool(tid), f"status={st}"):
        return
    st2, _ = call("PATCH", f"/api/tasks/{tid}", {"done": True})
    check("تعليم منجزة", st2 == 200, f"status={st2}")
    st3, _ = call("DELETE", f"/api/tasks/{tid}")
    check("حذف المهمة (تنظيف)", st3 == 200, f"status={st3}")


def test_reminders():
    section("التذكيرات (إنشاء ← حذف)")
    txt = f"{TAG} تذكير"
    when = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    st, _ = call("POST", "/api/reminders", {"text": txt, "remind_at": when})
    rid = _find_id("/api/reminders", txt)
    if not check("إنشاء تذكير", st == 200 and bool(rid), f"status={st}"):
        return
    st2, _ = call("DELETE", f"/api/reminders/{rid}")
    check("حذف التذكير (تنظيف)", st2 == 200, f"status={st2}")


def test_memory():
    section("الذاكرة (إضافة ← حذف)")
    txt = f"{TAG} معلومة"
    st, j = call("POST", "/api/memory", {"text": txt})
    mid = j.get("id") or _find_id("/api/memory", txt)
    if not check("إضافة معلومة", st == 200 and bool(mid), f"status={st}"):
        return
    st2, _ = call("DELETE", f"/api/memory/{mid}")
    check("حذف المعلومة (تنظيف)", st2 == 200, f"status={st2}")


def test_life():
    section("حياتي (عادة/مصروف/يومية — إنشاء ← حذف)")
    # habit
    name = f"{TAG} عادة"
    call("POST", "/api/life/habits", {"name": name})
    hid = _find_id("/api/life/habits", name, text_key="name")
    if check("إنشاء عادة", bool(hid)):
        st, _ = call("DELETE", f"/api/life/habits/{hid}")
        check("حذف العادة (تنظيف)", st == 200, f"status={st}")
    # expense
    note = f"{TAG} مصروف"
    call("POST", "/api/life/expenses", {"amount": 1, "note": note, "category": "test"})
    eid = _find_id("/api/life/expenses", note, text_key="note")
    if check("إنشاء مصروف", bool(eid)):
        st, _ = call("DELETE", f"/api/life/expenses/{eid}")
        check("حذف المصروف (تنظيف)", st == 200, f"status={st}")
    # journal
    jtxt = f"{TAG} يومية"
    call("POST", "/api/life/journal", {"text": jtxt})
    jid = _find_id("/api/life/journal", jtxt)
    if check("إنشاء يومية", bool(jid)):
        st, _ = call("DELETE", f"/api/life/journal/{jid}")
        check("حذف اليومية (تنظيف)", st == 200, f"status={st}")


def test_chat():
    section("الدردشة (العقل كامل)")
    st, j = call("POST", "/api/agent", {"message": "مرحبا كيفك؟", "lang": "ar"})
    reply = str(j.get("reply", "")).strip()
    check("رد ساندي على رسالة", st == 200 and len(reply) > 0,
          f"status={st}" if not reply else f"«{reply[:40]}…»")


def main():
    print(bold(f"\n🦞 فحص ساندي — {BASE_URL}\n"))
    password = os.getenv("SANDY_PASSWORD") or getpass.getpass("كلمة سر ساندي: ")
    started = time.time()

    if not test_auth(password):
        print(red("\n✗ فشل الدخول — وقفنا. تأكّد من كلمة السر والعنوان.\n"))
        sys.exit(1)

    test_read_only()
    test_daily_nudge()
    test_push()
    test_tasks()
    test_reminders()
    test_memory()
    test_life()
    test_chat()

    total = _passed + _failed
    elapsed = time.time() - started
    print("\n" + bold("─" * 44))
    verdict = green(f"نجح {_passed} من {total} ✓") if _failed == 0 \
        else red(f"فشل {_failed} من {total} ✗   (نجح {_passed})")
    print(f"  {verdict}   {dim(f'({elapsed:.1f}s)')}")
    if _failed:
        print(dim("  دوّر ع سطور ✗ الحمرا فوق — احكيلي أي وحدة وبصلحها."))
    print()
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
