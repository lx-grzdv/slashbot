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
        self.assertTrue(meme_replies._is_inspiring_scheduled_meme(reply))
        self.assertIsNone(meme_replies.PROMPT_LEAK.search(reply))

    def test_history_is_used_without_mixing_in_focus(self):
        with patch.object(meme_replies, "OPENAI_API_KEY", ""):
            reply = meme_replies._generate_scheduled_sp9_meme(
                ["клиент снова попросил перекрасить все кнопки"],
                meme_replies.SP9_SLOT_LLM_FOCUS["evening"],
                meme_replies.SP9_EVENING_FALLBACKS,
            )

        self.assertIsNotNone(reply)
        self.assertTrue(meme_replies._is_inspiring_scheduled_meme(reply))
        self.assertIsNone(meme_replies.PROMPT_LEAK.search(reply))

    def test_smaev_mode_uses_safe_parody_fallback(self):
        with patch.object(meme_replies, "OPENAI_API_KEY", ""):
            reply = meme_replies._generate_scheduled_sp9_meme(
                ["клиент добавил двадцать семь комментариев в макет"],
                meme_replies.SMAEV_LLM_FOCUS,
                meme_replies.SP9_EVENING_FALLBACKS,
                prefer_smaev=True,
            )

        self.assertIsNotNone(reply)
        self.assertTrue(meme_replies._is_inspiring_scheduled_meme(reply))
        self.assertRegex(
            reply.lower(),
            r"нагруз|подход|режим|техник|работ|результат|тяж[её]л",
        )
        self.assertNotRegex(reply.lower(), r"смаев|ребятушки|саров|завод")

    def test_scheduled_style_can_randomly_select_smaev(self):
        with patch.object(meme_replies.random, "choices", return_value=["smaev"]):
            style = meme_replies._pick_scheduled_style("evening", ["макет готов"])

        self.assertEqual(style, "smaev")

    def test_rejects_smaev_focus_prompt_leak(self):
        leaked = "РЕЖИМ «СИЛОВИК БЕЗ ГЛЯНЦА»: говори телеграфно про макет"
        self.assertFalse(meme_replies._is_valid_meme(leaked))
        self.assertIsNone(meme_replies._sanitize_llm_reply(leaked))

    def test_rejects_bleak_scheduled_meme_from_screenshot(self):
        bleak = (
            "После обеда у нас не прогресс, а ноукодный коматоз: "
            "макеты висят как мокрые сапоги на пне, и даже рендер, блэт, притворился мёртвым."
        )

        self.assertTrue(meme_replies._is_valid_meme(bleak))
        self.assertFalse(meme_replies._is_inspiring_scheduled_meme(bleak))

    def test_all_scheduled_fallbacks_are_inspiring(self):
        fallback_groups = (
            meme_replies.SP9_AFTERNOON_FALLBACKS,
            meme_replies.SP9_EVENING_FALLBACKS,
            meme_replies.SP9_EVENING_FRIDAY_FALLBACKS,
            meme_replies.DURDACH_FALLBACKS,
            meme_replies.SMAEV_FALLBACKS,
        )

        for fallbacks in fallback_groups:
            for template in fallbacks:
                reply = template.format(snippet="клиент добавил коммент в макет")
                with self.subTest(reply=reply):
                    self.assertTrue(meme_replies._is_inspiring_scheduled_meme(reply))

    def test_llm_retries_until_scheduled_reply_is_inspiring(self):
        bleak = "макеты висят, рендер мёртв"
        inspiring = "фигма взяла паузу, а мы нет — собрались и дожмём"
        with patch.object(
            meme_replies,
            "_generate_meme_with_llm",
            side_effect=(bleak, inspiring),
        ) as generate:
            reply = meme_replies._generate_meme_with_llm_retries(
                "",
                [],
                max_attempts=3,
                validator=meme_replies._is_inspiring_scheduled_meme,
            )

        self.assertEqual(reply, inspiring)
        self.assertEqual(generate.call_count, 2)

    def test_generic_fallbacks_end_with_forward_momentum(self):
        for template in meme_replies.MEME_TEMPLATES:
            reply = template.format(snippet="аналитика подоспела")
            with self.subTest(reply=reply):
                self.assertTrue(meme_replies._is_inspiring_scheduled_meme(reply))

        for template in meme_replies.MASHUP_TEMPLATES:
            reply = template.format(a="аналитика готова", b="коммент добавили")
            with self.subTest(reply=reply):
                self.assertTrue(meme_replies._is_inspiring_scheduled_meme(reply))

    def test_silence_prompts_are_supportive(self):
        self.assertTrue(
            meme_replies._is_inspiring_scheduled_meme(meme_replies.SILENCE_MEME_PROMPT)
        )
        self.assertTrue(
            meme_replies._is_inspiring_scheduled_meme(meme_replies.MEME_FORCE_FALLBACK_PROMPT)
        )


if __name__ == "__main__":
    unittest.main()
