"""Image editing (vision.py): Azure FLUX first, refusals before any call."""


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

