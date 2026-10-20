"""Card UI recovery: independent content, alternate history control, fresh tabs."""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import sp9_activity as activity
from test_sp9_activity import record

KEY = '25541fd053ce80baa9a9f6af58d04737'
TASK = {'title': 'Quiz SabioTrade', 'url': 'https://app.notion.com/p/' + KEY}
SINCE = date(2026, 10, 16)


class CardRecoveryTests(unittest.TestCase):
    def test_edited_control_opens_history_without_actions_menu(self):
        page = MagicMock()
        page.locator.return_value.count.return_value = 0
        activity._open_history(page)
        self.assertEqual(page.get_by_role.call_count, 1)
        self.assertTrue(page.get_by_role.call_args.kwargs['name'].match('Edited Sep 4'))
        page.get_by_text.assert_not_called()
        page.wait_for_function.assert_called_once()

    def test_history_uses_actions_when_edited_control_fails(self):
        page, edited, actions = MagicMock(), MagicMock(), MagicMock()
        page.locator.return_value.count.return_value = 0
        edited.first.click.side_effect = RuntimeError('Edited unavailable')
        page.get_by_role.side_effect = lambda role, **kw: actions if kw['name'] == 'Actions' else edited
        activity._open_history(page)
        actions.click.assert_called_once()
        page.get_by_text.assert_called_once_with('Updates & analytics', exact=True)
        page.wait_for_function.assert_called_once()

    def test_both_openers_failing_does_not_claim_history_is_complete(self):
        page = MagicMock()
        page.locator.return_value.count.return_value = 0
        page.get_by_role.return_value.first.click.side_effect = RuntimeError('Edited blocked')
        page.get_by_role.return_value.click.side_effect = RuntimeError('Actions blocked')
        with self.assertRaisesRegex(activity.capture.BrowserCaptureError, 'Не удалось открыть Updates'):
            activity._open_history(page)
        page.wait_for_function.assert_not_called()

    def test_missing_actions_cannot_block_verified_card_content(self):
        page = MagicMock()
        page.url = TASK['url']
        page.get_by_role.return_value.wait_for.side_effect = RuntimeError('Actions missing')
        data = {'content': [{'id': 'block', 'text': 'Brief', 'links': []}],
                'direct': [], 'discussion_present': True, 'history': []}
        page.evaluate.side_effect = lambda js, *args, **kw: copy.deepcopy(data) if js == activity._READ_JS else False
        with tempfile.TemporaryDirectory() as folder, patch.object(
            activity.capture, '_open_notion_page'
        ), patch.object(activity.capture, '_looks_logged_out', return_value=False), patch.object(
            activity, '_wait_for_card_identity', return_value='Quiz SabioTrade'
        ), patch.object(activity, '_read_history', return_value=({'history': []}, True)):
            result = activity._capture_card(page, TASK, Path(folder), SINCE)
        self.assertTrue(result['identity_verified'])
        self.assertTrue(all(result[k] for k in activity.COMPLETE_FLAGS))
        page.get_by_role.assert_not_called()

    def test_failure_keeps_stage_and_full_call_log_in_diagnostics(self):
        page = MagicMock()
        page.url = TASK['url']
        with tempfile.TemporaryDirectory() as folder, patch.object(
            activity.capture, '_open_notion_page', side_effect=RuntimeError('Timeout\nCall log: waiting for page')
        ):
            result = activity._capture_card(page, TASK, Path(folder), SINCE)
            saved = json.loads(next((Path(folder)/'diagnostics').glob('*.json')).read_text())
        self.assertFalse(result['content_complete'])
        self.assertEqual(saved['failure_details'][0]['stage'], 'navigation')
        self.assertIn('Call log:', saved['failure_details'][0]['message'])

    def test_cards_and_retry_each_get_a_new_tab(self):
        pages = [MagicMock(), MagicMock(), MagicMock()]
        ctx = MagicMock()
        ctx.new_page.side_effect = pages
        partial = {**record(), 'url': TASK['url'], 'comments_complete': False,
                   'updates_complete': False, 'errors': ['Timeout'], 'retryable': True}
        complete = {**record(), 'url': TASK['url']}
        second = {'title': 'Other card', 'url': 'https://app.notion.com/p/' + 'b'*32}
        with tempfile.TemporaryDirectory() as folder, patch.object(
            activity.capture, '_playwright', return_value=MagicMock()
        ), patch.object(activity.capture, '_launch_context', return_value=ctx), patch.object(
            activity, '_capture_card', side_effect=[partial, {**complete, 'url': second['url']}, complete]
        ) as read:
            activity.capture_card_activity([TASK, second], Path(folder), since=SINCE)
        self.assertEqual([call.args[0] for call in read.call_args_list], pages)
        for page in pages:
            page.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
