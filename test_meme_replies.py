import unittest
from unittest.mock import patch

import meme_replies


class ScheduledMemeSafetyTests(unittest.TestCase):
    def test_rejects_prompt_leaks_from_screenshots(self):
        leaked_replies = (
            "если ПОСЛЕОБЕДЕННЫЙ мем (15:00 МСК): полусон, макеты висят, прогресса ноль — значит мы обдудосились",
            "блэт Стиль можно как кринж S:P9, так и пафос «идущего к реке» / Дур-Дачника — звучит как оправдание перед клиентом",
        )

        for reply in leaked_replies:
            with self.subTest(reply=reply):
                self.assertFalse(meme_replies._is_valid_meme(reply))
                self.assertIsNone(meme_replies._sanitize_llm_reply(reply))

    def test_empty_history_uses_only_safe_slot_fallback(self):
        with patch.object(meme_replies, "OPENAI_API_KEY", ""):
            reply = meme_replies._generate_scheduled_sp9_meme(
                [],
                meme_replies.SP9_SLOT_LLM_FOCUS["afternoon"],
                meme_replies.SP9_AFTERNOON_FALLBACKS,
            )

        rendered_fallbacks = tuple(
            template.format(snippet="макет почти гуд")
            for template in meme_replies.SP9_AFTERNOON_FALLBACKS
        )
        self.assertIn(reply, rendered_fallbacks)
        self.assertTrue(meme_replies._is_valid_meme(reply))
        self.assertIsNone(meme_replies.PROMPT_LEAK.search(reply))

    def test_history_is_used_without_mixing_in_focus(self):
        with patch.object(meme_replies, "OPENAI_API_KEY", ""):
            reply = meme_replies._generate_scheduled_sp9_meme(
                ["клиент снова попросил перекрасить все кнопки"],
                meme_replies.SP9_SLOT_LLM_FOCUS["evening"],
                meme_replies.SP9_EVENING_FALLBACKS,
            )

        self.assertIsNotNone(reply)
        self.assertIsNone(meme_replies.PROMPT_LEAK.search(reply))


if __name__ == "__main__":
    unittest.main()
