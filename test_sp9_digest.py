import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
from zoneinfo import ZoneInfo

import sp9_digest
import sp9_capture
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


TZ = ZoneInfo("Europe/Moscow")


def task(title, status, due_date=None, url=None):
    return {
        "title": title,
        "status": status,
        "due_date": due_date,
        "url": url or f"https://app.notion.com/p/{title.replace(' ', '-')}",
        "assignees": [],
        "comments": 0,
        "confidence": 1.0,
    }


def snapshot(tasks, *, captured_at="2026-09-25T11:50:00+03:00"):
    counts = {
        "no_status": sum(item["status"] == "No Status" for item in tasks),
        "to_do": sum(item["status"] == "To Do" for item in tasks),
        "in_progress": sum(item["status"] == "In Progress" for item in tasks),
        "review": sum(item["status"] == "Review" for item in tasks),
        "completed": sum(item["status"] == "Completed" for item in tasks),
    }
    return {
        "captured_at": captured_at,
        "board_url": sp9_digest.BOARD_URL,
        "collection_complete": True,
        "board_counts": counts,
        "tasks": tasks,
        "updates": [],
        "motion_tasks": [],
        "warnings": [],
    }


class Sp9DigestTests(unittest.TestCase):
    def test_browser_timeout_is_retried_and_failure_notice_is_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sp9_digest, "DATA_DIR", Path(directory)), patch.object(
                sp9_digest, "_exclusive_run_lock"
            ) as lock, patch.object(sp9_capture, "_capture_sources", side_effect=PlaywrightTimeoutError("offline")) as capture, patch.object(
                sp9_digest, "_record_failure"
            ) as record, patch.object(sp9_digest, "notify_failure_once") as notice, patch.object(
                sp9_digest.time, "sleep"
            ) as sleep, patch.object(sp9_digest, "run_digest", side_effect=lambda **kwargs: sp9_capture.capture_sources(Path(directory))), redirect_stderr(io.StringIO()):
                lock.return_value.__enter__.return_value = True
                result = sp9_digest.main(["run", "--attempts", "3", "--retry-delay-seconds", "0"])

        self.assertEqual(result, 1)
        self.assertEqual(capture.call_count, 3)
        self.assertEqual(record.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        notice.assert_called_once()
        self.assertIsInstance(notice.call_args.args[0], sp9_capture.BrowserCaptureError)

    def test_telegram_transient_failure_is_retried_without_recapture(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "result": {"message_id": 42}}
        ).encode("utf-8")
        with patch.object(sp9_digest, "_bot_token", return_value="test-token"):
            with patch.object(
                sp9_digest.urllib.request,
                "urlopen",
                side_effect=[urllib.error.URLError("offline"), response],
            ) as urlopen:
                with patch.object(sp9_digest.time, "sleep") as sleep:
                    message_id = sp9_digest.send_telegram("test")

        self.assertEqual(message_id, 42)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_successful_today_uses_moscow_calendar_date(self):
        state = {"last_successful_send": "2026-09-30T21:30:00+00:00"}

        self.assertTrue(
            sp9_digest._successful_today(
                state, datetime(2026, 10, 1, 1, 0, tzinfo=TZ)
            )
        )

    def test_finishing_yesterdays_release_does_not_skip_todays_release(self):
        state = {'last_successful_send': '2026-10-12T11:50:00+03:00', 'last_successful_digest_date': '2026-10-09'}
        self.assertFalse(sp9_digest._successful_today(state, datetime(2026, 10, 12, 12, 10, tzinfo=TZ)))

    def test_successful_today_rejects_previous_date(self):
        state = {"last_successful_send": "2026-09-30T12:00:00+03:00"}

        self.assertFalse(
            sp9_digest._successful_today(
                state, datetime(2026, 10, 1, 11, 50, tzinfo=TZ)
            )
        )

    def test_todays_failure_notice_is_reused_as_edit_target(self):
        state = {
            "failure_notified_date": "2026-09-30",
            "failure_message_id": 21251,
        }
        run_time = datetime(2026, 9, 30, 12, 5, tzinfo=TZ)

        self.assertEqual(
            sp9_digest._replacement_message_id(state, run_time, None),
            21251,
        )
        self.assertEqual(
            sp9_digest._replacement_message_id(state, run_time, 999),
            999,
        )

    def test_old_failure_notice_is_not_reused(self):
        state = {
            "failure_notified_date": "2026-09-29",
            "failure_message_id": 21235,
        }
        run_time = datetime(2026, 9, 30, 12, 5, tzinfo=TZ)

        self.assertIsNone(
            sp9_digest._replacement_message_id(state, run_time, None)
        )

    def test_bundled_codex_candidates_cover_current_and_legacy_app_layouts(self):
        candidates = {str(path) for path in sp9_digest._bundled_codex_candidates()}

        self.assertIn(
            "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
            candidates,
        )
        self.assertIn(
            "/Applications/ChatGPT.app/Contents/Resources/codex",
            candidates,
        )
        self.assertIn(
            "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex",
            candidates,
        )

    def test_codex_path_falls_back_when_configured_location_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            bundled = Path(directory) / "codex"
            bundled.write_text("test", encoding="utf-8")
            with patch.object(sp9_digest, "CODEX_BIN", "/missing/old-codex"):
                with patch.object(
                    sp9_digest, "_bundled_codex_candidates", return_value=[bundled]
                ):
                    with patch.object(sp9_digest.shutil, "which", return_value=None):
                        self.assertEqual(sp9_digest._codex_path(), str(bundled))

    def test_edit_message_cannot_be_combined_with_no_send(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                sp9_digest.main(
                    ["run", "--no-send", "--edit-message-id", "21235"]
                )

    def test_status_and_deadline_changes_are_preserved_as_events(self):
        before = snapshot([task("Checkout", "To Do", "2026-09-26")])
        after = snapshot([task("Checkout", "In Progress", "2026-09-27")])

        events = sp9_digest.diff_tasks(before, after)

        self.assertEqual({item["kind"] for item in events}, {"status", "due_date"})
        self.assertTrue(all(item.get("fingerprint") for item in events))

    def test_unseen_completed_archive_card_is_not_reported_as_new(self):
        before = snapshot([])
        after = snapshot([task("Old archive item", "Completed")])

        self.assertEqual(sp9_digest.diff_tasks(before, after), [])

    def test_known_active_card_moving_to_completed_is_still_reported(self):
        before = snapshot([task("Launch", "Review")])
        after = snapshot([task("Launch", "Completed")])

        events = sp9_digest.diff_tasks(before, after)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "status")

    def test_new_overdue_is_high_priority(self):
        before = snapshot([task("Landing", "In Progress", "2026-09-25")])
        after = snapshot([task("Landing", "In Progress", "2026-09-24")])

        events = sp9_digest.diff_tasks(before, after)

        overdue = [item for item in events if item["kind"] == "overdue"]
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["priority"], 3)

    def test_render_is_compact_and_has_no_bullet_dots(self):
        data = snapshot(
            [
                task("Today task", "Review", "2026-09-25"),
                task("Old task", "In Progress", "2026-09-20"),
            ]
        )
        event = sp9_digest._event("update", data["tasks"][0], "новый комментарий", 4)

        text = sp9_digest.render_digest(
            data,
            [event],
            current_time=datetime(2026, 9, 25, 11, 55, tzinfo=TZ),
            weather="🌦 Питер: +13 °C · Лимасол: +28 °C",
        )

        self.assertIn("🆕 <b>Что изменилось</b>", text)
        self.assertIn("🔥 <b>Сегодня</b>", text)
        self.assertIn("Просрочено: 1", text)
        self.assertNotIn("\n•", text)
        self.assertLess(len(text), 1200)

    def test_render_shows_all_unique_changes_instead_of_hiding_after_three(self):
        data = snapshot([])
        events = [
            sp9_digest._event(
                "new_task",
                task(f"Change {index}", "To Do"),
                "новая задача в To Do",
                1,
            )
            for index in range(1, 7)
        ]

        text = sp9_digest.render_digest(
            data,
            events,
            current_time=datetime(2026, 10, 2, 11, 58, tzinfo=TZ),
        )

        for index in range(1, 7):
            self.assertIn(f"Change {index}", text)
        self.assertNotIn("Ещё изменений", text)

    def test_render_collapses_inbox_and_board_copy_of_same_status_move(self):
        board_event = sp9_digest._event(
            "status",
            task("Performance rewards", "Review"),
            "статус: In Progress → Review",
            3,
        )
        inbox_event = sp9_digest._event(
            "update",
            task("Performance rewards", "Review"),
            "superpasha9 изменил статус с In Progress на Review.",
            3,
        )

        text = sp9_digest.render_digest(
            snapshot([]),
            [inbox_event, board_event],
            current_time=datetime(2026, 10, 2, 11, 58, tzinfo=TZ),
        )

        self.assertEqual(text.count("Performance rewards"), 1)
        self.assertIn("superpasha9 изменил статус", text)
        self.assertNotIn("статус: In Progress", text)

    def test_today_block_shows_six_tasks_without_silent_truncation(self):
        tasks = [
            task(f"Today {index}", "In Progress", "2026-09-30")
            for index in range(1, 7)
        ]

        text = sp9_digest.render_digest(
            snapshot(tasks, captured_at="2026-09-30T12:00:00+03:00"),
            [],
            current_time=datetime(2026, 9, 30, 12, 0, tzinfo=TZ),
        )

        for index in range(1, 7):
            self.assertIn(f"Today {index}", text)
        self.assertNotIn("Ещё на сегодня", text)

    def test_today_block_includes_items_beyond_previous_display_limit(self):
        tasks = [
            task(f"Today {index}", "In Progress", "2026-09-30")
            for index in range(1, sp9_digest.MAX_TODAY_TASKS + 3)
        ]

        text = sp9_digest.render_digest(
            snapshot(tasks, captured_at="2026-09-30T12:00:00+03:00"),
            [],
            current_time=datetime(2026, 9, 30, 12, 0, tzinfo=TZ),
        )

        self.assertIn('Today 10', text)
        self.assertNotIn('Ещё на сегодня', text)

    def test_grouped_comments_keep_each_author_and_every_short_quote(self):
        item = task('PropChat', 'Completed')
        events = [dict(sp9_digest._event('update', item, f'{actor}: комментарий «{quote}»', 4),
                       author=actor, source_kind='comment', occurred_at='2026-10-10')
                  for actor, quote in [('Юлия', 'YouTube'), ('Юлия', 'Spotify'), ('Паша', 'Обложки готовы')]]
        text = sp9_digest.render_digest(snapshot([item]), events)
        self.assertEqual(text.count('>PropChat</a>'), 1)
        for value in ('Completed', 'Юлия', 'YouTube', 'Spotify', 'Паша', 'Обложки готовы'):
            self.assertIn(value, text)

    def test_long_comment_group_splits_entities_and_emoji_without_loss(self):
        text = 'Маркер & <текст> 😀 ' * 500
        parts = sp9_digest.split_digest(sp9_digest.html.escape(text))
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(sp9_digest._telegram_text_length(part), sp9_digest.MAX_TELEGRAM_TEXT)
        visible = '\n'.join(sp9_digest.html.unescape(sp9_digest.re.sub(r'<[^>]+>', '', p)) for p in parts)
        self.assertEqual(visible.count('Маркер'), 500)
        self.assertEqual(visible.count('<текст>'), 500)
        self.assertEqual(visible.count('😀'), 500)

    def test_status_refresh_updates_counts_from_direct_card_property(self):
        data = snapshot([task('PropChat', 'Review')])
        data['card_activity'] = [{'url': data['tasks'][0]['url'], 'content_complete': True,
                                 'page_text': 'Status\nCompleted\nDeadline', 'captured_at': '2026-10-12T12:05:00+03:00'}]
        sp9_digest._refresh_card_statuses(data)
        self.assertEqual(data['tasks'][0]['status'], 'Completed')
        self.assertEqual(data['board_counts']['review'], 0)
        self.assertEqual(data['board_counts']['completed'], 1)
        self.assertEqual(data['board_counts_at_capture']['review'], 1)

    def test_release_retry_resumes_only_unsent_parts_without_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / 'state.json'
            state = {'pending_events': [{'fingerprint': 'a'}, {'fingerprint': 'later'}],
                     'delivery_batch': {'messages': ['first', 'second'], 'message_ids': [],
                                        'replacement_id': None, 'fingerprints': ['a'], 'result': {'event_count': 1}}}
            with patch.object(sp9_digest, 'STATE_FILE', state_path), patch.object(sp9_digest, 'send_telegram', side_effect=[41, RuntimeError('network')]):
                with self.assertRaises(RuntimeError):
                    sp9_digest._deliver_saved_release(state)
            saved = json.loads(state_path.read_text())
            self.assertEqual(saved['delivery_batch']['message_ids'], [41])
            self.assertEqual(len(saved['pending_events']), 2)
            with patch.object(sp9_digest, 'STATE_FILE', state_path), patch.object(sp9_digest, 'capture_sources') as capture, patch.object(sp9_digest, 'send_telegram', return_value=42) as send:
                result = sp9_digest.run_digest(send=True)
            send.assert_called_once_with('second')
            capture.assert_not_called()
            self.assertEqual(result['message_ids'], [41, 42])
            saved = json.loads(state_path.read_text())
            self.assertEqual(saved['pending_events'], [{'fingerprint': 'later'}])
            self.assertNotIn('delivery_batch', saved)

    def test_motion_status_mismatch_is_detected(self):
        data = snapshot([task("Локализация видео в Академии", "Completed")])
        data["motion_tasks"] = [
            {
                "title": "Локализация видео в Академии",
                "url": None,
                "status": "In Progress",
                "due_date": None,
                "assignee": "Илья",
                "progress": None,
                "confidence": 1.0,
            }
        ]

        mismatches = sp9_digest.motion_mismatches(data)

        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["motion_status"], "In Progress")

    def test_completed_and_done_are_equivalent_motion_statuses(self):
        data = snapshot([task("Локализация видео", "Completed")])
        data["motion_tasks"] = [
            {
                "title": "Локализация видео",
                "url": None,
                "status": "Done",
                "due_date": None,
                "assignee": "Илья",
                "progress": None,
                "confidence": 1.0,
            }
        ]

        self.assertEqual(sp9_digest.motion_mismatches(data), [])

    def test_incomplete_extraction_is_rejected(self):
        data = snapshot([task("Only one", "To Do")])
        data["board_counts"] = {
            "no_status": 8,
            "to_do": 4,
            "in_progress": 15,
            "review": 7,
            "completed": 9,
        }

        problems = sp9_digest.validate_snapshot(data)

        self.assertTrue(any("активных карточек" in item for item in problems))

    def test_completed_archive_and_motion_leak_do_not_break_active_coverage(self):
        notion_task = task("Active", "In Progress")
        leaked_motion = task(
            "Motion copy",
            "In Progress",
            url="https://sabio-tasks.superpasha9000.chatgpt.site/motion-copy",
        )
        data = snapshot([notion_task, leaked_motion])
        data["board_counts"] = {
            "no_status": 0,
            "to_do": 0,
            "in_progress": 1,
            "review": 0,
            "completed": 99,
        }
        data["collection_complete"] = False

        normalized = sp9_digest.normalize_snapshot(data)

        self.assertEqual([item["title"] for item in normalized["tasks"]], ["Active"])
        self.assertEqual(sp9_digest.validate_snapshot(normalized), [])

    def test_update_fingerprint_survives_translation_and_paraphrase(self):
        russian = {
            "task_title": "Referral offer",
            "task_url": "https://app.notion.com/p/referral?pvs=25",
            "kind": "mention",
            "details": "Ekaterina Chuprina упомянула Aleksei Gruzdev.",
            "occurred_at": "2026-09-22",
            "confidence": 0.98,
        }
        english = {
            **russian,
            "task_url": "https://app.notion.com/p/referral?pvs=5",
            "details": "Ekaterina Chuprina mentioned you; assignee Aleksei Gruzdev.",
        }
        first = sp9_digest.update_events({"updates": [russian]}, set())
        repeated = sp9_digest.update_events(
            {"updates": [english]}, {first[0]["fingerprint"]}
        )

        self.assertEqual(repeated, [])

    def test_localized_update_kind_has_same_identity(self):
        base = {
            "task_title": "Referral offer",
            "task_url": "https://app.notion.com/p/referral",
            "details": "Ekaterina Chuprina упомянула вас.",
            "occurred_at": "2026-09-22",
            "confidence": 0.99,
        }
        english_kind = {**base, "kind": "mention"}
        russian_kind = {**base, "kind": "Упоминание"}

        self.assertEqual(
            sp9_digest._update_fingerprint(english_kind),
            sp9_digest._update_fingerprint(russian_kind),
        )

    def test_comment_paraphrase_with_wrote_does_not_repeat_sent_event(self):
        previous = {
            "task_title": "Available assets for each tariff",
            "task_url": "https://app.notion.com/p/available-assets?pvs=25",
            "kind": "comment",
            "details": (
                "Dary Saura попросил Ilmira Akhmetkhanova проверить и завершить "
                "оставшиеся детали задачи и передать её технической команде."
            ),
            "occurred_at": "2026-10-08",
            "confidence": 0.98,
        }
        first = sp9_digest.update_events({"updates": [previous]}, set())
        descriptions = [
            "Dary Saura написала Ilmira Akhmetkhanova, что задача создана пару "
            "месяцев назад, попросила проверить оставшиеся детали, завершить "
            "их и передать технической команде.",
            "Dary Saura wrote to Ilmira Akhmetkhanova asking to finish the task.",
            "Dary Saura оставила комментарий с просьбой завершить задачу.",
            "Dary Saura ответила Ilmira Akhmetkhanova: нужно завершить задачу.",
        ]
        for description in descriptions:
            with self.subTest(description=description):
                current = {
                    **previous,
                    "task_url": "https://app.notion.com/p/available-assets?d=comment&pvs=5",
                    "details": description,
                }
                self.assertEqual(sp9_digest._update_actor(description), "dary saura")
                self.assertEqual(
                    sp9_digest.update_events(
                        {"updates": [current]},
                        {first[0]["fingerprint"]},
                        since=datetime(2026, 10, 8, tzinfo=TZ).date(),
                        previous_updates=[previous],
                    ),
                    [],
                )

    def test_new_comment_survives_paraphrase_of_older_same_author_comment(self):
        base = {
            "task_title": "Available assets for each tariff",
            "task_url": "https://app.notion.com/p/available-assets",
            "kind": "comment",
            "occurred_at": "2026-10-08",
            "confidence": 0.98,
        }
        previous = {**base, "details": "Dary Saura попросила завершить задачу."}
        first = sp9_digest.update_events({"updates": [previous]}, set())
        old = {**base, "details": "Dary Saura написала: нужно завершить задачу."}
        new = {**base, "details": "Dary Saura написала: техническая команда приняла результат."}

        events = sp9_digest.update_events(
            {"updates": [new, old]},
            {first[0]["fingerprint"]},
            since=datetime(2026, 10, 8, tzinfo=TZ).date(),
            previous_updates=[previous],
        )

        self.assertEqual([event["details"] for event in events], [new["details"]])

    def test_old_or_undated_inbox_items_are_not_new(self):
        base = {
            "task_title": "Old task",
            "task_url": "https://app.notion.com/p/old",
            "kind": "mention",
            "details": "новое упоминание",
            "confidence": 0.99,
        }
        old = {**base, "occurred_at": "2026-09-22"}
        undated = {**base, "occurred_at": None}
        current = {**base, "occurred_at": "2026-09-28"}

        events = sp9_digest.update_events(
            {"updates": [old, undated, current]},
            set(),
            since=datetime(2026, 9, 26, tzinfo=TZ).date(),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["details"], "новое упоминание в задаче")

    def test_same_visible_comment_is_not_repeated_when_date_drifts_one_day(self):
        previous = {
            "task_title": "Performance rewards",
            "task_url": "https://app.notion.com/p/performance-rewards",
            "kind": "comment",
            "details": "superpasha9 оставил комментарий: «макет для комментариев».",
            "occurred_at": "2026-09-28",
            "confidence": 0.99,
        }
        current = {
            **previous,
            "occurred_at": "2026-09-29",
            "details": "superpasha9 оставил комментарий: «макет для комментариев» и приложил ссылку на Figma.",
        }

        events = sp9_digest.update_events(
            {"updates": [current]},
            set(),
            since=datetime(2026, 9, 29, tzinfo=TZ).date(),
            previous_updates=[previous],
        )

        self.assertEqual(events, [])

    def test_english_update_narration_has_russian_fallback(self):
        update = {
            "task_title": "Performance rewards",
            "task_url": "https://app.notion.com/p/performance",
            "kind": "property_update",
            "details": "Ilmira and Pasha updated the status; it remains In Progress.",
            "occurred_at": "2026-09-23",
            "confidence": 0.96,
        }

        events = sp9_digest.update_events({"updates": [update]}, set())

        self.assertEqual(events[0]["details"], "обновлены свойства задачи")
        self.assertNotIn("updated", events[0]["details"])

    def test_comments_and_property_updates_outrank_mentions(self):
        base = {
            "task_url": "https://app.notion.com/p/task",
            "occurred_at": "2026-09-28",
            "confidence": 0.99,
        }
        updates = [
            {
                **base,
                "task_title": "Mention",
                "kind": "mention",
                "details": "Pasha mentioned you.",
            },
            {
                **base,
                "task_title": "Property",
                "kind": "property_update",
                "details": "Status changed.",
            },
            {
                **base,
                "task_title": "Comment",
                "kind": "comment",
                "details": "Dary Saura: нужен ответ.",
            },
        ]

        events = sp9_digest.update_events({"updates": updates}, set())
        priorities = {item["title"]: item["priority"] for item in events}

        self.assertGreater(priorities["Comment"], priorities["Property"])
        self.assertGreater(priorities["Property"], priorities["Mention"])

    def test_comments_by_different_people_are_not_collapsed(self):
        base = {
            "task_title": "About company",
            "task_url": "https://app.notion.com/p/about",
            "kind": "comment",
            "occurred_at": "2026-09-25",
            "confidence": 0.9,
        }
        first = {**base, "details": "Dary Saura: нужен перевод."}
        second = {**base, "details": "Юлия Е.: перевод готов."}

        events = sp9_digest.update_events({"updates": [first, second]}, set())

        self.assertEqual(len({item["fingerprint"] for item in events}), 2)

    def test_new_same_author_comment_gets_new_oldest_first_occurrence(self):
        base = {
            "task_title": "About company",
            "task_url": "https://app.notion.com/p/about",
            "kind": "comment",
            "occurred_at": "2026-09-25",
            "confidence": 0.9,
        }
        old = {**base, "details": "Dary Saura: первый комментарий."}
        first_run = sp9_digest.update_events({"updates": [old]}, set())
        new = {**base, "details": "Dary Saura: второй комментарий."}

        second_run = sp9_digest.update_events(
            {"updates": [new, old]}, {first_run[0]["fingerprint"]}
        )

        self.assertEqual(
            [item["details"] for item in second_run],
            ["Dary Saura: второй комментарий."],
        )


if __name__ == "__main__":
    unittest.main()
