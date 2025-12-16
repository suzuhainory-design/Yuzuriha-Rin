"""Tests for image descriptions utility."""

import json
import tempfile
from pathlib import Path
from src.utils.image_descriptions import ImageDescriptions


class TestImageDescriptions:
    """Tests for ImageDescriptions class."""

    def setup_method(self):
        """Create a temporary JSON file for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_json = Path(self.temp_dir) / "test_image_descriptions.json"
        
        # Create test data
        self.test_data = {
            "./assets/stickers/general/limao_yongyu/01.gif": "礼貌用语表情包",
            "./assets/stickers/rin/kending_haode/01.png": "好的，表示肯定",
            "./src/frontend/images/avatar/user.png": "用户头像",
            "./assets/stickers/rin/sample/01.webp": "Rin 表情包"
        }
        
        with open(self.temp_json, "w", encoding="utf-8") as f:
            json.dump(self.test_data, f, ensure_ascii=False)
        
        # Override the JSON path for testing
        ImageDescriptions._json_path = self.temp_json
        ImageDescriptions._cache = {}

    def test_get_description_existing(self):
        """Test getting description for an existing image."""
        alter = ImageDescriptions()
        desc = alter.get_description("./assets/stickers/general/limao_yongyu/01.gif")
        assert desc == "礼貌用语表情包"

    def test_get_description_nonexistent(self):
        """Test getting description for a non-existent image."""
        alter = ImageDescriptions()
        desc = alter.get_description("./assets/stickers/nonexistent/test.png")
        assert desc is None

    def test_path_normalization(self):
        """Test that paths are normalized correctly."""
        alter = ImageDescriptions()
        
        # Test with leading slash
        desc1 = alter.get_description("/api/stickers/general/limao_yongyu/01.gif")
        assert desc1 == "礼貌用语表情包"

        # Test with static assets path mapping back to src
        desc2 = alter.get_description("static/images/avatar/user.png")
        assert desc2 == "用户头像"

        # Test with Windows-style separators
        desc3 = alter.get_description("assets\\stickers\\rin\\kending_haode\\01.png")
        assert desc3 == "好的，表示肯定"

    def test_singleton_pattern(self):
        """Test that ImageDescriptions is a singleton."""
        alter1 = ImageDescriptions()
        alter2 = ImageDescriptions()
        assert alter1 is alter2

    def test_cache_behavior(self):
        """Test that cache is used after first load."""
        alter = ImageDescriptions()
        
        # First call loads from JSON
        desc1 = alter.get_description("./src/frontend/images/avatar/user.png")
        assert desc1 == "用户头像"
        
        # Modify JSON file
        new_data = {"./src/frontend/images/avatar/user.png": "新的描述"}
        with open(self.temp_json, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False)
        
        # Cache should still return old value
        desc2 = alter.get_description("./src/frontend/images/avatar/user.png")
        assert desc2 == "用户头像"
        
        # Clear cache and reload
        alter._cache = {}
        desc3 = alter.get_description("./src/frontend/images/avatar/user.png")
        assert desc3 == "新的描述"

    def test_malformed_json_handling(self):
        """Test that malformed JSON doesn't crash the utility."""
        # Write malformed JSON
        with open(self.temp_json, "w") as f:
            f.write("{ invalid json }")
        
        alter = ImageDescriptions()
        alter._cache = {}  # Clear cache
        
        # Should return None without crashing
        desc = alter.get_description("./assets/stickers/test.png")
        assert desc is None

    def test_api_prefix_normalization(self):
        """Test that API sticker URLs resolve to sticker descriptions."""
        alter = ImageDescriptions()
        desc = alter.get_description("/api/stickers/rin/sample/01.webp")
        assert desc == "Rin 表情包"

    def test_missing_json_file(self):
        """Test behavior when JSON file doesn't exist."""
        ImageDescriptions._json_path = Path(self.temp_dir) / "nonexistent.json"
        alter = ImageDescriptions()
        alter._cache = {}  # Clear cache
        
        # Should return None without crashing
        desc = alter.get_description("./assets/stickers/test.png")
        assert desc is None
