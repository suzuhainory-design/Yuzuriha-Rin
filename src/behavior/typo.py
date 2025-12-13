"""
Typo Injection Module (Human-like IME Mis-selection)

This version focuses on realism:
- Strongly prefer word-level same-pinyin mistakes.
- Char-level typos are heavily restricted to common IME confusions.
- Avoid rare / obscure characters: "better no typo than weird typo".
- Candidate selection uses scoring + thresholds (not uniform random).

Public API is kept stable:
    inject_typo(text, typo_rate) -> (has_typo, typo_text, pos, original)
    should_recall_typo(recall_rate) -> bool
"""

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import jieba
from pypinyin import lazy_pinyin

from src.infrastructure.utils.logger import unified_logger, LogCategory


# ----------------------------------------------------------------------
# Same Pinyin Finder with frequency
# ----------------------------------------------------------------------
@dataclass
class SamePinyinFinder:
    """
    Build same-pinyin word candidates with frequency information.

    We intentionally do NOT enumerate the entire CJK Unicode range.
    Single-character candidates are derived ONLY from dictionary statistics.
    """

    words: Iterable[str] = field(default_factory=list)
    word_freq: Dict[str, int] = field(default_factory=dict)

    _pinyin_to_words: Dict[str, List[str]] = field(init=False, default_factory=dict)
    _char_freq: Dict[str, int] = field(init=False, default_factory=dict)
    _pinyin_to_chars: Dict[str, List[str]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        # Build word index
        for w in self.words:
            p = self.word_to_pinyin(w)
            if not p:
                continue
            self._pinyin_to_words.setdefault(p, []).append(w)

        # Sort candidates by frequency descending
        for p, ws in self._pinyin_to_words.items():
            ws.sort(key=lambda x: self.word_freq.get(x, 1), reverse=True)

        # Build char statistics and char index from dictionary
        self._build_char_stats()

    @classmethod
    def from_dict_file(cls, path: str) -> "SamePinyinFinder":
        """
        Build from jieba dict file (jieba dict format: word freq tag).
        """
        words: List[str] = []
        freq: Dict[str, int] = {}

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue

                w = parts[0].strip()
                if not w:
                    continue

                # frequency (default 1)
                n = 1
                if len(parts) > 1:
                    try:
                        n = int(parts[1])
                    except Exception:
                        n = 1

                words.append(w)
                freq[w] = n

        return cls(words=words, word_freq=freq)

    @staticmethod
    def word_to_pinyin(text: str) -> str:
        """Convert text to tone-less concatenated pinyin."""
        return "".join(lazy_pinyin(text, errors="ignore"))

    def get_word_candidates(self, word: str, limit: int = 30) -> List[str]:
        """Return same-pinyin word candidates, sorted by frequency."""
        p = self.word_to_pinyin(word)
        if not p:
            return []
        cands = self._pinyin_to_words.get(p, [])
        out = [w for w in cands if w != word]
        return out[:limit]

    def get_char_candidates(self, ch: str, limit: int = 12) -> List[str]:
        """
        Return same-pinyin single-character candidates derived from dictionary.
        Sorted by single-char frequency descending.
        """
        p = self.word_to_pinyin(ch)
        if not p:
            return []
        cands = self._pinyin_to_chars.get(p, [])
        out = [c for c in cands if c != ch]
        return out[:limit]

    def get_word_freq(self, word: str) -> int:
        return int(self.word_freq.get(word, 1))

    def get_char_freq(self, ch: str) -> int:
        return int(self._char_freq.get(ch, 0))

    def _build_char_stats(self) -> None:
        """
        Build single-character frequency from dictionary, then index chars by pinyin.

        We keep only top-N frequent chars to avoid rare character injection.
        """
        char_freq: Dict[str, int] = {}

        # Aggregate freq from both single-char entries and multi-char words
        for w, f in self.word_freq.items():
            if not w:
                continue
            # Count each character in common words (gives better robustness than only len==1)
            for ch in w:
                if "\u4e00" <= ch <= "\u9fff":
                    char_freq[ch] = char_freq.get(ch, 0) + max(1, int(f))

        self._char_freq = char_freq

        # Keep only the top frequent chars (hard ban on rare chars)
        TOP_CHAR_LIMIT = 3500
        top_chars = sorted(char_freq.items(), key=lambda x: x[1], reverse=True)[
            :TOP_CHAR_LIMIT
        ]

        pinyin_to_chars: Dict[str, List[str]] = {}
        for ch, _f in top_chars:
            p = self.word_to_pinyin(ch)
            if not p:
                continue
            pinyin_to_chars.setdefault(p, []).append(ch)

        # Sort each pinyin bucket by char frequency
        for p, chars in pinyin_to_chars.items():
            chars.sort(key=lambda c: char_freq.get(c, 0), reverse=True)

        self._pinyin_to_chars = pinyin_to_chars


# ----------------------------------------------------------------------
# Typo Injector (Human-like)
# ----------------------------------------------------------------------
class TypoInjector:
    """
    Human-like typo injection.

    Strategy:
    1) Prefer word-level same-pinyin replacements (IME mis-selection).
    2) Char-level typo is heavily restricted and may be skipped entirely.
    """

    # -----------------------------
    # Behavior knobs (tune here)
    # -----------------------------

    # Char-level typo should be rarer than word-level (realistic).
    CHAR_TYPO_ACCEPT_RATE = 0.25

    # Word typo acceptance threshold: if best candidate too weak -> no typo
    WORD_ACCEPT_THRESHOLD = 0.35

    # Char typo acceptance threshold: even stricter
    CHAR_ACCEPT_THRESHOLD = 0.55

    # Skip doing generic char typo on sentence-ending particles.
    # This prevents "weird a/ba/ne" variants at the end.
    END_PARTICLES = set("啊吧呢呀啦哦哎嘛呗哈诶")

    # A curated IME-like confusion whitelist for particles & common function words.
    # This is the highest realism / best ROI trick.
    PARTICLE_CONFUSIONS: Dict[str, List[str]] = {
        "啊": ["阿"],
        "呀": ["吖", "丫"],  # optional, still common enough
        "吧": ["八", "巴", "叭", "罢"],
        "呢": ["那", "哪", "讷", "呐"],
        "啦": ["拉"],
        "哦": ["噢", "欧"],
        "哎": ["唉", "诶"],
        "嘛": ["吗"],
        "的": ["地", "得"],
        "在": ["再"],
        "再": ["在"],
        "那": ["哪"],
        "哪": ["那"],
    }

    # For some characters, we ban same-pinyin replacements unless they are from whitelist.
    STRICT_CHAR_WHITELIST_ONLY = set("啊呀吧呢啦哦哎嘛的在再那哪叭吖")

    def __init__(
        self,
        same_pinyin_dict_path: Optional[str] = None,
        max_word_candidates: int = 30,
    ):
        """
        Args:
            same_pinyin_dict_path: Optional path to jieba dict for pinyin matching.
            max_word_candidates: Max same-pinyin word candidates per token.
        """
        self.max_word_candidates = max_word_candidates
        self.same_pinyin_dict_path = self._resolve_dict_path(same_pinyin_dict_path)

        self._finder: Optional[SamePinyinFinder] = None
        self._finder_loaded = False

        # English keyboard neighbor typos (unchanged)
        self.english_keyboard_neighbors = {
            "q": ["w", "a"],
            "w": ["q", "e", "s"],
            "e": ["w", "r", "d"],
            "r": ["e", "t", "f"],
            "t": ["r", "y", "g"],
            "y": ["t", "u", "h"],
            "u": ["y", "i", "j"],
            "i": ["u", "o", "k"],
            "o": ["i", "p", "l"],
            "p": ["o", "l"],
            "a": ["q", "s", "z"],
            "s": ["a", "w", "d", "x"],
            "d": ["s", "e", "f", "c"],
            "f": ["d", "r", "g", "v"],
            "g": ["f", "t", "h", "b"],
            "h": ["g", "y", "j", "n"],
            "j": ["h", "u", "k", "m"],
            "k": ["j", "i", "l"],
            "l": ["k", "o", "p"],
            "z": ["a", "x"],
            "x": ["z", "s", "c"],
            "c": ["x", "d", "v"],
            "v": ["c", "f", "b"],
            "b": ["v", "g", "n"],
            "n": ["b", "h", "m"],
            "m": ["n", "j"],
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def inject_typo(  # TODO: receive real configs
        self, text: str, typo_rate: float = 0.05
    ) -> Tuple[bool, Optional[str], Optional[int], Optional[str]]:
        """
        Potentially inject a typo into the text.

        Usage example:
            injector = TypoInjector()
            has_typo, typo_text, pos, original = injector.inject_typo(
                "这个功能的制作过程非常复杂",
                typo_rate=0.2,
            )

        Returns:
            has_typo: bool
            typo_text: Optional[str]
            typo_position: Optional[int]
            original_char_or_token: Optional[str]
        """
        if not text or random.random() > typo_rate:
            return False, None, None, None

        # 1) Word-level typo (main path)
        word_result = self._apply_word_typo(text)
        if word_result:
            return True, *word_result

        # 2) Char-level typo (rare, restricted)
        char_result = self._apply_char_typo(text)
        if char_result:
            return True, *char_result

        return False, None, None, None

    def should_recall_typo(self, recall_rate: float) -> bool:
        """Decide whether to recall and fix a typo."""
        return random.random() < recall_rate

    # ------------------------------------------------------------------
    # Word-level typo
    # ------------------------------------------------------------------
    def _apply_word_typo(self, text: str) -> Optional[Tuple[str, int, str]]:
        finder = self._get_finder()
        if not finder or not self._contains_cjk(text):
            return None

        # Use tokenize() to obtain exact offsets (avoid find() pitfalls)
        tokens = list(jieba.tokenize(text))
        if not tokens:
            return None

        # Do not always typo in the beginning part (looks unnatural)
        min_start = max(1, len(text) // 3)

        # Collect candidate replacements
        scored: List[Tuple[float, int, int, str, str]] = []
        for token, start, end in tokens:
            if start < min_start:
                continue
            if not self._contains_cjk(token):
                continue
            if len(token) < 2:
                continue  # word typo prefers multi-char tokens

            alts = finder.get_word_candidates(token, limit=self.max_word_candidates)
            if not alts:
                continue

            # Score top candidates only (fast + realistic)
            top_alts = alts[: min(len(alts), 12)]
            for alt in top_alts:
                score = self._score_word_replacement(
                    text=text,
                    start=start,
                    end=end,
                    original=token,
                    replacement=alt,
                    finder=finder,
                )
                scored.append((score, start, end, token, alt))

        if not scored:
            return None

        # Pick best scored replacement
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, start, end, token, replacement = scored[0]

        # If not good enough, skip typo
        if best_score < self.WORD_ACCEPT_THRESHOLD:
            return None

        typo_text = text[:start] + replacement + text[end:]
        return typo_text, start, token

    def _score_word_replacement(
        self,
        *,
        text: str,
        start: int,
        end: int,
        original: str,
        replacement: str,
        finder: SamePinyinFinder,
    ) -> float:
        """
        Heuristic scoring for word-level IME mistakes.

        Signals:
        - Replacement word frequency (dominant)
        - Local context plausibility (lightweight)
        - Penalize replacements that look too "off"
        """
        # Frequency base
        f = finder.get_word_freq(replacement)
        base = math.log(f + 1.0)

        # Local context: consider neighbors around the token
        left = text[max(0, start - 6) : start]
        right = text[end : min(len(text), end + 6)]

        # Very cheap context heuristic:
        # If replacement + neighbor forms a common word in dictionary, boost.
        bonus = 0.0
        if left:
            cand = left[-2:] + replacement  # small join
            bonus += 0.15 * math.log(finder.get_word_freq(cand) + 1.0)
        if right:
            cand = replacement + right[:2]
            bonus += 0.15 * math.log(finder.get_word_freq(cand) + 1.0)

        # Penalty: replacement identical or contains non-CJK
        if replacement == original:
            return -1.0
        if not self._contains_cjk(replacement):
            return -1.0

        # Soft length penalty (IME errors usually keep length same)
        length_pen = 0.0
        if len(replacement) != len(original):
            length_pen = 0.8

        # Convert to a 0~1-ish score using sigmoid
        raw = base * 0.9 + bonus - length_pen
        score = 1.0 / (1.0 + math.exp(-0.25 * (raw - 2.0)))
        return float(score)

    # ------------------------------------------------------------------
    # Char-level typo (restricted)
    # ------------------------------------------------------------------
    def _apply_char_typo(self, text: str) -> Optional[Tuple[str, int, str]]:
        # Char typos should be rarer than word typos
        if random.random() > self.CHAR_TYPO_ACCEPT_RATE:
            return None

        finder = self._get_finder()
        if not finder:
            return None

        min_pos = max(1, len(text) // 3)

        candidates: List[Tuple[float, int, str, str]] = []
        for idx, ch in enumerate(text):
            if idx < min_pos:
                continue

            # Prefer not messing with sentence-ending particles in generic mode
            if idx == len(text) - 1 and ch in self.END_PARTICLES:
                # Only allow whitelist confusion (e.g. 啊->阿), otherwise skip
                if ch not in self.PARTICLE_CONFUSIONS:
                    continue

            # 1) Whitelist confusions dominate (highest realism)
            if ch in self.PARTICLE_CONFUSIONS:
                for alt in self.PARTICLE_CONFUSIONS[ch]:
                    score = self._score_char_replacement(ch, alt, finder, strong=True)
                    candidates.append((score, idx, ch, alt))
                continue

            # 2) For strict chars: do NOT use generic same-pinyin candidates
            if ch in self.STRICT_CHAR_WHITELIST_ONLY:
                continue

            # 3) Generic same-pinyin single-char candidates (still frequency-filtered)
            if self._is_cjk_char(ch):
                alts = finder.get_char_candidates(ch, limit=10)
                for alt in alts:
                    score = self._score_char_replacement(ch, alt, finder, strong=False)
                    if score >= self.CHAR_ACCEPT_THRESHOLD:
                        candidates.append((score, idx, ch, alt))

            # 4) English neighbor typos
            elif ch.lower() in self.english_keyboard_neighbors:
                for alt in self.english_keyboard_neighbors[ch.lower()]:
                    alt2 = alt.upper() if ch.isupper() else alt
                    candidates.append((0.75, idx, ch, alt2))  # fixed decent score

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, idx, original, replacement = candidates[0]

        # Hard acceptance threshold
        if best_score < self.CHAR_ACCEPT_THRESHOLD:
            return None

        typo_text = text[:idx] + replacement + text[idx + 1 :]
        return typo_text, idx, original

    def _score_char_replacement(
        self, original: str, replacement: str, finder: SamePinyinFinder, *, strong: bool
    ) -> float:
        """
        Score char replacement.

        strong=True means whitelist confusion (e.g., 啊->阿) which is usually very natural.
        strong=False means generic same-pinyin char swap (more risky).
        """
        if replacement == original:
            return 0.0
        if not self._is_cjk_char(replacement):
            return 0.0

        # Prefer high-frequency replacement chars
        rf = finder.get_char_freq(replacement)
        of = finder.get_char_freq(original)

        # If replacement is extremely rare compared to original, penalize heavily
        # This kills things like 啊->锕 (rare)
        ratio = (rf + 1.0) / (of + 10.0)

        base = math.log(rf + 1.0) / 10.0  # compress scale
        if strong:
            base += 0.35  # whitelist bonus

        # Rare penalty
        if ratio < 0.05:
            base -= 1.2
        elif ratio < 0.15:
            base -= 0.6

        # Clamp to [0,1]
        score = max(0.0, min(1.0, base))
        return float(score)

    # ------------------------------------------------------------------
    # Finder / utilities
    # ------------------------------------------------------------------
    def _get_finder(self) -> Optional[SamePinyinFinder]:
        if self._finder_loaded:
            return self._finder

        self._finder_loaded = True
        try:
            if self.same_pinyin_dict_path and self.same_pinyin_dict_path.exists():
                self._finder = SamePinyinFinder.from_dict_file(
                    str(self.same_pinyin_dict_path)
                )
            else:
                # If no dict, we cannot do safe frequency-based typo injection.
                self._finder = None
        except Exception as exc:
            unified_logger.warning(
                f"Failed to init SamePinyinFinder: {exc}",
                category=LogCategory.BEHAVIOR,
            )
            self._finder = None

        return self._finder

    def _resolve_dict_path(self, explicit_path: Optional[str]) -> Optional[Path]:
        if explicit_path:
            p = Path(explicit_path)
            return p if p.exists() else None

        project_root = Path(__file__).resolve().parent.parent.parent
        data_dir = project_root / "data"
        for name in ("jieba/dict.txt.big", "jieba/dict.txt"):
            candidate = data_dir / name
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text)

    @staticmethod
    def _is_cjk_char(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff"
