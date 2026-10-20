"""Published counter changes: signs, original dates and delivery checkpoint."""
import copy
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import sp9_digest as digest
from test_sp9_digest import task, snapshot, TZ

NOW = datetime(2026, 10, 19, 12, tzinfo=TZ)


class SummaryTests(unittest.TestCase):
    def test_signed_changes_are_shown_in_published_footer(self):
        data = snapshot([task(str(i), 'To Do', '2026-10-18') for i in range(42)])
        data['board_counts'].update(in_progress=14, review=17, no_status=7)
        data['previous_published_metrics'] = {
            'overdue': 41, 'in_progress': 13, 'review': 16, 'no_status': 10,
        }
        text = digest.render_editorial_digest(data, [], {'rows': [], 'omitted': []}, current_time=NOW)
        self.assertIn('⏰ Просрочено: 42 (+1) · В работе: 14 (+1) · '
                      'На ревью: 17 (+1) · Без статуса: 7 (-3)', text)

    def test_first_release_and_unchanged_counters_have_no_parentheses(self):
        data = snapshot([])
        for baseline in (None, {'overdue': 0, 'in_progress': 0, 'review': 0, 'no_status': 0}):
            data['previous_published_metrics'] = baseline
            self.assertEqual(digest._summary_line(data, NOW.date()),
                '⏰ Просрочено: 0 · В работе: 0 · На ревью: 0 · Без статуса: 0')

    def test_legacy_friday_release_keeps_friday_overdue_count_on_monday(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'friday.json'
            friday = snapshot([task('Due Friday', 'To Do', '2026-10-16')],
                              captured_at='2026-10-16T11:47:00+03:00')
            digest._atomic_json(path, friday)
            state = {'last_snapshot': str(path), 'last_successful_send': '2026-10-16T11:50:00+03:00',
                     'last_successful_digest_date': '2026-10-16'}
            baseline = digest._published_summary(state)
            self.assertEqual(baseline['metrics']['overdue'], 0)
            monday = copy.deepcopy(friday)
            monday['previous_published_metrics'] = baseline['metrics']
            self.assertIn('Просрочено: 1 (+1)', digest._summary_line(monday, NOW.date()))
            # An unsent later snapshot is not proof of previously published counts.
            friday['captured_at'] = '2026-10-16T12:00:00+03:00'
            digest._atomic_json(path, friday)
            self.assertIsNone(digest._published_summary(state))

    def test_unpublished_snapshot_is_not_a_comparison_baseline(self):
        self.assertIsNone(digest._published_summary({'last_snapshot': 'unused.json'}))

    def test_delivery_failure_keeps_old_metrics_until_confirmed_retry(self):
        old = {'release_date': '2026-10-16', 'metrics': {
            'overdue': 38, 'in_progress': 15, 'review': 16, 'no_status': 7}}
        current = {'overdue': 42, 'in_progress': 14, 'review': 17, 'no_status': 7}
        state = {**digest._default_state(), 'last_published_summary': old,
                 'delivery_batch': {'messages': ['post'], 'message_ids': [], 'replacement_id': None,
                                    'fingerprints': [], 'release_date': '2026-10-19',
                                    'result': {'summary_metrics': current}}}
        with tempfile.TemporaryDirectory() as folder, patch.object(
            digest, 'STATE_FILE', Path(folder)/'state.json'
        ), patch.object(digest, '_now', return_value=NOW), patch.object(
            digest, 'send_telegram', side_effect=[RuntimeError('offline'), 123]
        ):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                digest._deliver_saved_release(state)
            self.assertEqual(state['last_published_summary'], old)
            digest._deliver_saved_release(state)
            saved = digest._load_json(digest.STATE_FILE, {})
            self.assertEqual(saved['last_published_summary'],
                             {'release_date': '2026-10-19', 'metrics': current})


if __name__ == '__main__':
    unittest.main()
