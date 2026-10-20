"""Regressions from 15 October: descriptions are not cards; invalid sources expire."""
import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import sp9_capture as capture
import sp9_digest as digest
from test_sp9_digest import task, snapshot, TZ

KEY = 'a' * 32
URL = 'https://app.notion.com/p/' + KEY
NOW = datetime(2026, 10, 15, 12, tzinfo=TZ)


def inventory():
    return {'version': 1, 'complete': True, 'captured_at': NOW.isoformat(),
            'board_counts': {'no_status': 1, 'to_do': 0, 'in_progress': 0, 'review': 0, 'completed': 99},
            'cards': [{'id': KEY, 'title': 'EEAT. Страница «О компании»', 'url': URL, 'status': 'No Status',
                       'text': 'EEAT. Страница «О компании»\nДоработка main site в рамках EEAT улучшений'}]}


class SourceIntegrityTests(unittest.TestCase):
    def test_description_mistaken_for_task_is_removed_using_real_card_ids(self):
        data = snapshot([task('EEAT', 'No Status', url=URL),
                         {**task('Доработка main site в рамках EEAT улучшений', 'No Status'), 'url': None}],
                        captured_at=NOW.isoformat())
        fixed = digest._apply_board_inventory(data, {'board_inventory': inventory()})
        self.assertEqual(len(fixed['tasks']), 1)
        self.assertEqual(fixed['tasks'][0]['title'], 'EEAT. Страница «О компании»')
        self.assertEqual(fixed['board_inventory_corrections']['excluded'], ['Доработка main site в рамках EEAT улучшений'])
        self.assertEqual(digest.validate_snapshot(fixed), [])

    def test_real_card_missed_by_model_is_retained_for_direct_reading(self):
        fixed = digest._apply_board_inventory(snapshot([]), {'board_inventory': inventory()})
        self.assertEqual(fixed['tasks'][0]['url'], URL)
        self.assertEqual(fixed['tasks'][0]['assignees'], [])
        self.assertIsNone(fixed['tasks'][0]['due_date'])
        self.assertEqual(fixed['board_inventory_corrections']['added_ids'], [KEY])

    def test_slug_url_matches_same_id_and_dom_status_overrides_ocr(self):
        data = snapshot([task('EEAT', 'Review', '2026-10-20', url='https://app.notion.com/p/EEAT-' + KEY)])
        fixed = digest._apply_board_inventory(data, {'board_inventory': inventory()})
        self.assertEqual(fixed['tasks'][0]['due_date'], '2026-10-20')
        self.assertEqual(fixed['tasks'][0]['status'], 'No Status')

    def test_incomplete_or_ambiguous_inventory_is_rejected(self):
        for issue in ('missing', 'duplicate', 'url', 'version', 'cards_type', 'card_type', 'counts_type'):
            with self.subTest(issue=issue):
                source = inventory()
                if issue == 'missing': source['board_counts']['no_status'] = 2
                if issue == 'duplicate': source['cards'].append(copy.deepcopy(source['cards'][0]))
                if issue == 'url': source['cards'][0]['url'] = 'https://other.example/' + KEY
                if issue == 'version': source['version'] = 99
                if issue == 'cards_type': source['cards'] = None
                if issue == 'card_type': source['cards'] = [None]
                if issue == 'counts_type': source['board_counts'] = None
                with self.assertRaises(RuntimeError):
                    digest._apply_board_inventory(snapshot([]), {'board_inventory': source})

    def test_normalization_deduplicates_different_slugs_for_one_card(self):
        data = snapshot([task('EEAT', 'No Status', url=URL), task('Other OCR', 'No Status', url='https://app.notion.com/p/EEAT-'+KEY)])
        self.assertEqual(len(digest.normalize_snapshot(data)['tasks']), 1)

    def test_dom_description_remains_inside_one_physical_card(self):
        page = MagicMock()
        labels = ['No Status', 'To Do', 'In Progress', 'Review', 'Completed']
        raw = {'headers': [{'status': s, 'count': '1' if s=='No Status' else '99+' if s=='Completed' else '0'} for s in labels],
               'groups': [[{'id': KEY, 'title': 'EEAT', 'text': 'EEAT\nDescription with another title'}], [], [], [], []]}
        page.evaluate.return_value = raw
        result = capture._board_inventory(page)
        self.assertEqual(len(result['cards']), 1)
        self.assertEqual(result['cards'][0]['text'], 'EEAT\nDescription with another title')
        raw['headers'][0]['count'] = '2'
        with self.assertRaisesRegex(capture.BrowserCaptureError, 'прочитано 1 из 2'):
            capture._board_inventory(page)

    def test_notion_navigation_waits_for_real_ui_after_commit(self):
        page = MagicMock()
        capture._open_notion_page(page, URL)
        page.goto.assert_called_once_with(URL, wait_until='commit', timeout=45000)
        page.locator.assert_called_with('.notion-page-content')
        page.locator.return_value.wait_for.assert_called_once_with(state='attached', timeout=45000)

    def test_login_is_reported_when_notion_ui_does_not_load(self):
        page = MagicMock()
        page.url = 'https://app.notion.com/login'
        page.locator.return_value.wait_for.side_effect = RuntimeError('UI timeout')
        with self.assertRaisesRegex(capture.BrowserCaptureError, 'не авторизована'):
            capture._open_notion_page(page, URL)

    def test_invalid_structured_output_is_classified_for_source_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder)
            manifest = {'captured_at': NOW.isoformat(), 'board_images': ['fixture.jpg']}
            for raw in ('{broken', '[]', '{"tasks": null}', '{"tasks": [null]}'):
                with self.subTest(raw=raw):
                    (destination/'extracted_snapshot.json').write_text(raw)
                    with patch.object(digest, '_codex_path', return_value='/fake/codex'), patch.object(
                        digest.subprocess, 'run', return_value=MagicMock(returncode=0, stdout='fixture log')
                    ):
                        with self.assertRaises(digest.SnapshotValidationError):
                            digest.extract_snapshot(manifest, destination)


class FailureNoticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state_patch = patch.object(digest, 'STATE_FILE', Path(temporary.name)/'state.json')
        state_patch.start()
        self.addCleanup(state_patch.stop)
        now_patch = patch.object(digest, '_now', return_value=NOW)
        now_patch.start()
        self.addCleanup(now_patch.stop)
        self.send_patch = patch.object(digest, 'send_telegram', return_value=21425)
        self.edit_patch = patch.object(digest, 'edit_telegram', return_value=21425)
        self.send = self.send_patch.start()
        self.edit = self.edit_patch.start()
        self.addCleanup(self.send_patch.stop)
        self.addCleanup(self.edit_patch.stop)

    def test_new_failure_reason_updates_same_notice_without_duplicate(self):
        digest.notify_failure_once(RuntimeError('Page.goto timeout'))
        digest.notify_failure_once(RuntimeError('Неполный снимок'))
        self.send.assert_called_once()
        self.edit.assert_called_once()
        self.assertEqual(self.edit.call_args.args[1], 21425)
        self.assertIn('Неполный снимок', self.edit.call_args.args[0])
        state = digest._load_json(digest.STATE_FILE, {})
        self.assertEqual(state['failure_message_id'], 21425)

    def test_unchanged_failure_reason_does_not_edit_again(self):
        digest.notify_failure_once(RuntimeError('offline'))
        digest.notify_failure_once(RuntimeError('offline'))
        self.send.assert_called_once()
        self.edit.assert_not_called()

    def test_successful_release_is_not_replaced_by_failure(self):
        digest._atomic_json(digest.STATE_FILE, {
            **digest._default_state(), 'last_successful_send': NOW.isoformat(),
            'last_successful_digest_date': NOW.date().isoformat(),
        })
        digest.notify_failure_once(RuntimeError('offline'))
        self.send.assert_not_called()
        self.edit.assert_not_called()

    def test_warning_already_replaced_by_delivered_part_is_not_overwritten(self):
        digest._atomic_json(digest.STATE_FILE, {
            **digest._default_state(), 'failure_notified_date': NOW.date().isoformat(),
            'failure_message_id': 21425,
            'delivery_batch': {'message_ids': [21425], 'messages': ['first', 'second']},
        })
        digest.notify_failure_once(RuntimeError('second part offline'))
        self.send.assert_not_called()
        self.edit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
