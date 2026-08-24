"""Error taxonomy: the typed errors carry the right status/code, the Flask app
wires the handler, and the broad-`except Exception` count only ratchets down."""

import os
import pathlib
import re

os.environ.setdefault("JWT_SECRET", "test-secret-for-errors")

from app.errors import (  # noqa: E402
    AuthError,
    ConfigError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    SandyError,
    ValidationError,
)

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "cloud" / "app"

# Frozen count of broad `except Exception` in app/. Broad catches are fine at
# true edges (optional integrations, background jobs, index creation); this only
# stops the count from *growing*. Lower it as sites adopt typed exceptions.
#
# 405 -> 407 on 15 Aug 2026: error_tracking.py added two, both at the edge this
# baseline exists to allow. One wraps the scrubber, where anything that throws
# must drop the event rather than send it unscrubbed; the other wraps the SDK's
# own startup, because error reporting may never be the reason the app is down.
# Raising a ratchet should always cost a sentence explaining why — that is the
# difference between a considered exception and quiet drift.
# 407 -> 410 on 20 Aug 2026: wiring Sandy's body to her features added three,
# each at a boundary where the optional half must never break the real one.
#
#   robot_expression.express  — a face, a melody, a light. The robot may be
#       unplugged, on another network, or not owned at all (a phone-only
#       account). Losing a saved goal because a light failed would be a far
#       worse bug than the silence this replaced. Deliberately ONE catch at the
#       edge rather than one per helper — an earlier draft had three, which hid
#       the interesting failures along with the boring ones.
#
#   scene_store._actuate      — per device, so one device the owner does not
#       have cannot cancel the rest of the scene. The name is collected and
#       returned in `missed`, not swallowed.
#
#   graph.recent_turns_for_user — a cross-channel memory read. If it fails she
#       answers with slightly less context; if it raised, she would not answer.
#
# Raising a ratchet should always cost a sentence explaining why — that is the
# difference between a considered exception and quiet drift.
# 410 -> 412 on 20 Aug 2026: real accounts and robot pairing added two.
#
#   devices_api.api_nodes_unpair — the factory-reset publish. A board that is
#       unplugged must not block someone from releasing it before a sale; the
#       reply reports which half succeeded instead.
#
#   voice_ws.tools — the tool dispatch guard, now that a voice session runs as
#       whichever account is on the line rather than one global owner.
#
# Deliberately NOT added: the account deletion sweep and the pairing claim check
# both catch `PyMongoError` by name. A delete that misses a collection reports
# success while keeping the diary, and a claim check that swallows an error
# would hand out a robot somebody already owns — neither is a place to catch
# everything.
#   node_store._is_legacy_owner — a security question: "may this account take
#       over a robot somebody already holds?" If the lookup fails we do not
#       know, and not knowing must answer **no**. Catching everything here and
#       returning False is the safe direction, which is why it is broad.
#   camera_client.start_snapshot — the ingest counters printed with every
#       capture. Diagnostics must never be able to break the thing they are
#       diagnosing, and this line exists precisely because the previous
#       diagnostic silently stopped running when the request stopped waiting.
#   life_snapshot._safe + context_builder._safe_life_snapshot — الوعي بحياته
#       زيادة، مش شرط للرد. قائمة وحدة وقعت ما بتجوز تسكّت ساندي — بتخسر سطر
#       من خلفيتها وبتكمّل.
#   context_builder._safe_life_search — البحث بكل قوائمه لقاء سؤاله. زيادة
#       معرفة، مش شرط للرد.
#   context_builder._safe_index_life — فهرسة قوائمه للبحث بالمعنى. لو ما في
#       مخزن تضمينات بتتخطّى بصمت، وبيضلّ البحث الحرفي شغّالًا.
BROAD_EXCEPT_BASELINE = 417


def test_subtypes_have_expected_status_and_code():
    assert (ValidationError().http_status, ValidationError().code) == (400, "invalid_request")
    assert (AuthError().http_status, AuthError().code) == (401, "unauthorized")
    assert (ForbiddenError().http_status, ForbiddenError().code) == (403, "forbidden")
    assert (NotFoundError().http_status, NotFoundError().code) == (404, "not_found")
    assert (RateLimitError().http_status, RateLimitError().code) == (429, "too_many_attempts")
    assert (ConfigError().http_status, ConfigError().code) == (503, "not_configured")


def test_all_subtypes_are_sandy_errors():
    for cls in (ValidationError, AuthError, ForbiddenError, NotFoundError, RateLimitError, ConfigError):
        assert issubclass(cls, SandyError)


def test_per_raise_override():
    err = ValidationError("bad id", code="bad_task_id", http_status=422)
    assert err.code == "bad_task_id"
    assert err.http_status == 422
    assert str(err) == "bad id"


def test_create_app_registers_the_handler():
    from app.api.server import create_app

    app = create_app(mongo_db=None, semantic_memory_stats_fn=lambda: {})
    client = app.test_client()

    @app.route("/__raise_test")
    def _raise():
        raise ForbiddenError()

    resp = client.get("/__raise_test")
    assert resp.status_code == 403
    assert resp.get_json() == {"error": "forbidden"}


def test_broad_except_count_does_not_grow():
    total = 0
    for path in APP_DIR.rglob("*.py"):
        total += len(re.findall(r"except Exception", path.read_text(encoding="utf-8")))
    assert total <= BROAD_EXCEPT_BASELINE, (
        f"Broad `except Exception` rose to {total} (baseline {BROAD_EXCEPT_BASELINE}). "
        "Prefer a typed app.errors.SandyError on request paths; broad catches are "
        "for true edges (optional integrations, background jobs)."
    )
