"""Tests for image editing features: image_agent.py + vision.py"""

from app.features.image_agent import ensure_image_state


class TestEnsureImageState:
    def test_none_session_returns_default(self):
        state = ensure_image_state(None)
        assert state["active_image"] is None
        assert state["active_image_bytes"] is None
        assert state["history"] == []
        assert state["pending_image_action"] is None

    def test_non_dict_session_returns_default(self):
        state = ensure_image_state("not a dict")
        assert state["active_image"] is None

    def test_existing_session_gets_image_state(self):
        session = {}
        state = ensure_image_state(session)
        assert "image_state" in session
        assert state is session["image_state"]

    def test_active_image_bytes_field_present(self):
        session = {"image_state": {"active_image": {"user_request": "test"}, "history": []}}
        state = ensure_image_state(session)
        assert "active_image_bytes" in state

    def test_existing_bytes_preserved(self):
        fake_bytes = b"PNG_DATA"
        session = {
            "image_state": {
                "active_image": None,
                "active_image_bytes": fake_bytes,
                "history": [],
                "pending_image_action": None,
            }
        }
        state = ensure_image_state(session)
        assert state["active_image_bytes"] == fake_bytes

    def test_history_defaults_to_list(self):
        session = {"image_state": {"active_image": None}}
        state = ensure_image_state(session)
        assert isinstance(state["history"], list)

    def test_called_twice_returns_same_state(self):
        session = {}
        s1 = ensure_image_state(session)
        s2 = ensure_image_state(session)
        assert s1 is s2


class TestEditImageWithAzure:
    """Tests for edit_image_with_azure (Azure FLUX-backed)."""

    def test_empty_prompt_returns_none(self):
        from app.features.vision import edit_image_with_azure

        result = edit_image_with_azure(b"image", "")
        assert result is None

    def test_empty_image_returns_none(self):
        from app.features.vision import edit_image_with_azure

        result = edit_image_with_azure(b"", "edit")
        assert result is None

    def test_calls_azure_flux(self):
        from unittest.mock import patch
        from app.features.vision import edit_image_with_azure

        with patch(
            "app.integrations.azure_flux.edit_image_azure",
            return_value=b"edited",
        ) as mock_edit:
            result = edit_image_with_azure(b"original", "make it blue")
        assert result == b"edited"
        mock_edit.assert_called_once()

