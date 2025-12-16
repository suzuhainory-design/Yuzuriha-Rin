"""Image description utility for providing text alternatives to images."""

import json
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse


class ImageDescriptions:
    """Provides text descriptions for local image files."""

    _instance = None
    _json_path: Path = Path(__file__).parent.parent.parent / "assets" / "configs" / "image_descriptions.json"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
        return cls._instance

    def get_description(self, image_path: str) -> Optional[str]:
        """
        Get description for a local image file.

        Args:
            image_path: Relative path to the image file

        Returns:
            Description string if available, None otherwise
        """
        candidates = self._generate_path_candidates(image_path)
        if not candidates:
            return None

        # Check cache first
        for candidate in candidates:
            if candidate in self._cache:
                return self._cache[candidate]

        # Load from JSON file
        self._load_from_json()

        # Return from cache after loading
        for candidate in candidates:
            description = self._cache.get(candidate)
            if description:
                # Cache the lookup alias to speed up future queries
                primary = candidates[0]
                if candidate != primary:
                    self._cache[primary] = description
                return description
        return None

    def _generate_path_candidates(self, image_path: Optional[str]) -> List[str]:
        """Generate possible cache lookup keys from an input image path."""
        if not image_path:
            return []

        raw_path = str(image_path).strip()
        if not raw_path:
            return []

        parsed = urlparse(raw_path)
        if parsed.scheme and parsed.netloc:
            raw_path = parsed.path

        # Remove query strings and fragments
        raw_path = raw_path.split("?", 1)[0].split("#", 1)[0]

        normalized = raw_path.replace("\\", "/")

        # Remove query strings, fragments handled above, now normalize prefixes
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.lstrip("/")

        if not normalized:
            return []

        prefixes = ("api/", "assets/", "data/", "static/")
        base_candidates: List[str] = []
        queue = [normalized]
        seen = set()

        while queue:
            current = queue.pop(0)
            if not current or current in seen:
                continue
            seen.add(current)
            base_candidates.append(current)
            for prefix in prefixes:
                if current.startswith(prefix):
                    queue.append(current[len(prefix):])

        final_candidates: List[str] = []
        candidate_set = set()

        def add_candidate(value: str):
            value = value.strip()
            if not value:
                return
            normalized_value = value.replace("\\", "/")
            if normalized_value not in candidate_set:
                candidate_set.add(normalized_value)
                final_candidates.append(normalized_value)

        for candidate in base_candidates:
            add_candidate(candidate)
            add_candidate(f"./{candidate}")

            if candidate.startswith("stickers/"):
                tail = candidate[len("stickers/") :]
                add_candidate(f"assets/stickers/{tail}")
                add_candidate(f"./assets/stickers/{tail}")

            if candidate.startswith("assets/"):
                tail = candidate[len("assets/") :]
                add_candidate(f"stickers/{tail}")
                add_candidate(f"./assets/{tail}")  # Ensure ./assets prefix exists

            if candidate.startswith("api/stickers/"):
                tail = candidate[len("api/") :]
                add_candidate(tail)
                if tail.startswith("stickers/"):
                    sticker_tail = tail[len("stickers/") :]
                    add_candidate(f"assets/stickers/{sticker_tail}")
                    add_candidate(f"./assets/stickers/{sticker_tail}")

            if candidate.startswith("static/"):
                tail = candidate[len("static/") :]
                add_candidate(f"src/frontend/{tail}")
                add_candidate(f"./src/frontend/{tail}")

        return final_candidates

    def _load_from_json(self):
        """Load image descriptions from JSON file into cache."""
        if not self._json_path.exists():
            return

        try:
            with open(self._json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._cache = data
        except Exception:
            # Silently ignore errors, cache remains empty or unchanged
            pass


# Singleton instance
image_descriptions = ImageDescriptions()
