import copy
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import sp9_activity as activity
import sp9_digest as digest
from test_sp9_digest import task, snapshot

URL = 'https://app.notion.com/p/3e241fd053ce808abf83ffb03dd7853a'
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=ZoneInfo('Europe/Moscow'))


def record(author='Aleksei Gruzdev', text='Добавил схему покупки сессий.', time='16h'):
    return {
        'title': 'Checkout', 'url': URL, 'captured_at': NOW.isoformat(),
        'content_complete': True, 'comments_complete': True, 'updates_complete': True,
        'content': [{'id': 'block1', 'text': 'Задача'}], 'content_hash': 'before',
        'comments': [{'author': author, 'text': text, 'time': time}],
        'history': [{'header': f'{author} commented in Checkout', 'time': time,
                     'text': author + '\n' + text,
                     'items': [{'url': URL + '?d=thread1', 'text': author + '\n' + text}]}],
        'errors': [],
    }


class ActivityTests(unittest.TestCase):
    def test_updates_expansion_replaces_text_without_requiring_new_headers(self):
        page = MagicMock()
        entry = {'header': 'Aleksei Gruzdev edited Checkout', 'time': '1 hour ago', 'text': 'Начало', 'items': []}
        expanded = {**entry, 'text': 'Начало и раскрытые блоки'}
        page.evaluate.side_effect = [{'history': [entry], 'panel_text': 'Начало\nView 70 more'},
                                    {'history': [expanded], 'panel_text': 'Начало и раскрытые блоки'}]
        more = page.locator.return_value.get_by_text.return_value
        more.count.side_effect = [1, 0]
        page.locator.return_value.inner_text.return_value = 'Начало\nView 70 more'
        with patch.object(activity, '_open_history'):
            data, complete = activity._read_history(page, NOW.date(), NOW)
        self.assertTrue(complete)
        self.assertEqual(data['history'], [expanded])
        self.assertEqual(page.wait_for_function.call_args.kwargs['arg'], 'Начало\nView 70 more')

    def test_relative_times_cross_midnight_and_yearless_dates_cross_year(self):
        self.assertEqual(activity.ui_date('16 hours ago', NOW), date(2026, 10, 8))
        self.assertEqual(activity.ui_date('36m', NOW), date(2026, 10, 9))
        self.assertEqual(activity.ui_date('Sep 28', NOW), date(2026, 9, 28))
        self.assertEqual(activity.ui_date('Dec 31', NOW.replace(month=1, day=2)), date(2025, 12, 31))
        self.assertIsNone(activity.ui_date('нечитаемо', NOW))

    def test_recovery_adds_discussion_link_without_repeating_delivered_comment(self):
        before = record()
        before['history'] = []
        before['updates_complete'] = False
        after = record()
        seen = {activity.source_updates(before)[0]['fingerprint']}
        data = {'card_activity': [after], 'updates': []}
        events = activity.activity_events(data, None, seen, date(2026, 10, 8))
        self.assertEqual(len(events), 1)
        reconciled = digest._reconcile_card_events(events, [], data, {'card_activity': [before]}, seen, [])
        self.assertEqual(reconciled, [])
        self.assertIn(events[0]['fingerprint'], seen)

    def test_task_identity_survives_title_and_parent_url_changes(self):
        self.assertEqual(activity.card_key(URL), activity.card_key('https://app.notion.com/p/New-title-3e241fd053ce808abf83ffb03dd7853a?pvs=25'))
        self.assertEqual(activity.card_key(URL), activity.card_key('https://app.notion.com/p/board-11541fd053ce8023873af02a304d24cd?p=3e241fd053ce808abf83ffb03dd7853a&pm=s'))

    def test_own_comment_is_read_with_source_author_and_discussion_link(self):
        events = activity.activity_events({'card_activity': [record()]}, None, set(), date(2026, 10, 8))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['author'], 'Aleksei Gruzdev')
        self.assertIn('Добавил схему', events[0]['raw_text'])
        self.assertEqual(events[0]['discussion_url'], URL + '?d=thread1')

    def test_old_or_undated_comments_do_not_become_new(self):
        for time in ['Sep 28', 'нечитаемо']:
            with self.subTest(time=time):
                self.assertEqual(activity.activity_events({'card_activity': [record(time=time)]}, None, set(), date(2026, 10, 8)), [])

    def test_date_drift_and_display_paraphrase_do_not_repeat_source(self):
        old = record()
        current = record(time='1d')
        current['title'] = 'Чекаут'
        seen = {activity.source_updates(old)[0]['fingerprint']}
        self.assertEqual(activity.activity_events({'card_activity': [current]}, None, seen, date(2026, 10, 8)), [])

    def test_new_reply_in_same_thread_survives_old_comment(self):
        old = record()
        current = copy.deepcopy(old)
        current['history'][0]['items'].append({'url': URL + '?d=thread1', 'text': 'Ilmira Akhmetkhanova\nМакеты согласованы.'})
        events = activity.activity_events({'card_activity': [current]}, {'card_activity': [old]}, set(), date(2026, 10, 8))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['author'], 'Ilmira Akhmetkhanova')

    def test_link_inside_comment_cannot_invent_a_comment_or_author(self):
        data = record()
        data['history'][0]['items'].append({'url': 'https://www.figma.com/design/example?node-id=12&d=spoof', 'text': 'Fake author\nFake comment'})
        self.assertEqual(len(activity.source_updates(data)), 1)

    def test_reaction_count_does_not_change_comment_identity(self):
        old = record()
        item = old['history'][0]['items'][0]
        item.update({'author': 'Aleksei Gruzdev', 'body_text': old['comments'][0]['text'], 'body_complete': True})
        current = copy.deepcopy(old)
        current['history'][0]['items'][0]['text'] += '\n❤️\n1'
        seen = {activity.source_updates(old)[0]['fingerprint']}
        self.assertEqual(activity.activity_events({'card_activity': [current]}, {'card_activity': [old]}, seen, date(2026, 10, 8)), [])

    def test_unreadable_old_comment_does_not_block_recent_coverage(self):
        history = [{'header': 'Pasha commented in Checkout', 'time': 'Sep 21', 'items': [{'body_complete': False}]}]
        self.assertTrue(activity.comments_readable(history, date(2026, 10, 8), NOW))
        history[0]['time'] = '1h'
        self.assertFalse(activity.comments_readable(history, date(2026, 10, 8), NOW))

    def test_new_identical_comment_gets_new_occurrence(self):
        old = record()
        current = copy.deepcopy(old)
        current['history'].insert(0, copy.deepcopy(current['history'][0]))
        seen = {activity.source_updates(old)[0]['fingerprint']}
        events = activity.activity_events({'card_activity': [current]}, {'card_activity': [old]}, seen, date(2026, 10, 8))
        self.assertEqual(len(events), 1)

    def test_different_authors_and_two_comments_are_preserved(self):
        own = record()
        other = record(author='Ilmira Akhmetkhanova')
        self.assertNotEqual(activity.source_updates(own)[0]['fingerprint'], activity.source_updates(other)[0]['fingerprint'])
        own['history'][0]['items'].append({'url': URL + '?d=thread1', 'text': 'Aleksei Gruzdev\nДобавил документацию.'})
        self.assertEqual(len(activity.source_updates(own)), 2)

    def test_content_diff_has_no_invented_actor_and_needs_complete_baseline(self):
        before = record()
        after = record()
        after['content_hash'] = 'changed'
        after['updates_complete'] = False
        after['comments_complete'] = False
        events = activity.activity_events({'card_activity': [after]}, {'card_activity': [before]}, set(), date(2026, 10, 9))
        self.assertEqual([e['kind'] for e in events], ['content'])
        self.assertNotIn('author', events[0])
        before['content_complete'] = False
        self.assertEqual(activity.activity_events({'card_activity': [after]}, {'card_activity': [before]}, set(), date(2026, 10, 9)), [])

    def test_new_source_seed_does_not_report_entire_historical_content(self):
        self.assertEqual(activity.activity_events({'card_activity': [record(time='Sep 28')]}, None, set(), date(2026, 10, 8)), [])

    def test_recent_completed_and_disappeared_active_card_are_targets(self):
        current = snapshot([task('Finished', 'Completed', url=URL)])
        previous = snapshot([task('Missing', 'In Progress')])
        self.assertEqual({t['title'] for t in activity.targets(current, previous)}, {'Finished', 'Missing'})

    def test_partial_capture_is_visible_in_empty_digest(self):
        data = snapshot([task('Checkout', 'In Progress', url=URL)])
        data['card_activity'] = [record()]
        data['card_activity'][0]['updates_complete'] = False
        data['activity_coverage'] = activity.coverage(data)
        rendered = digest.render_digest(data, [], current_time=NOW)
        self.assertIn('В проверенных карточках', rendered)
        self.assertIn('Не полностью прочитано карточек: 1', rendered)
        self.assertIn(' — Updates', rendered)
        self.assertIn('Checkout', rendered)
        self.assertIn('Updates 0/1', rendered)

    def test_oversized_release_splits_without_hiding_changes_today_or_coverage(self):
        data = snapshot([task('Due today', 'Review', '2026-10-09')])
        data['card_activity'] = [record()]
        data['activity_coverage'] = activity.coverage(data)
        events = [digest._event('update', task(f'Change {i}', 'To Do'), 'x' * 300, 4) for i in range(40)]
        rendered = digest.render_digest(data, events, current_time=NOW)
        parts = digest.split_digest(rendered)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(digest._telegram_text_length(part), digest.MAX_TELEGRAM_TEXT)
        for i in range(40):
            self.assertIn(f'>Change {i}</a>', '\n'.join(parts))
        self.assertNotIn('Ещё изменений:', rendered)
        self.assertIn('Due today', rendered)
        self.assertIn('Проверено:', rendered)

    def test_first_card_scan_catches_previous_workday_missing_own_comment(self):
        self.assertEqual(digest._activity_since({'captured_at': NOW.isoformat()}, NOW, []), date(2026, 10, 8))
        monday = NOW.replace(day=12)
        self.assertEqual(digest._activity_since(None, monday, []), date(2026, 10, 9))

    def test_midnight_creates_new_overdue_without_deadline_edit(self):
        before = snapshot([task('Late', 'To Do', '2026-10-08')], captured_at='2026-10-08T12:00:00+03:00')
        after = snapshot([task('Late', 'To Do', '2026-10-08')], captured_at=NOW.isoformat())
        self.assertEqual([e['kind'] for e in digest.diff_tasks(before, after)], ['overdue'])

    def test_assignee_order_does_not_create_change_but_assignment_does(self):
        before = snapshot([task('Checkout', 'To Do')])
        before['tasks'][0]['assignees'] = ['Pasha', 'Ilmira']
        after = copy.deepcopy(before)
        after['tasks'][0]['assignees'].reverse()
        self.assertEqual(digest.diff_tasks(before, after), [])
        after['tasks'][0]['assignees'].append('Aleksei')
        self.assertEqual([e['kind'] for e in digest.diff_tasks(before, after)], ['assignees'])

    def test_already_sent_inbox_comment_seeds_card_identity(self):
        source = record(author='Ilmira Akhmetkhanova')
        data = snapshot([])
        data['card_activity'] = [source]
        inbox = {'task_title': 'Checkout', 'task_url': URL, 'kind': 'comment', 'details': 'Ilmira Akhmetkhanova написала: схема покупки готова.', 'occurred_at': '2026-10-08', 'confidence': 1}
        data['updates'] = [inbox]
        seen = {digest._update_fingerprint(inbox)}
        events = activity.activity_events(data, None, seen, date(2026, 10, 8))
        self.assertEqual(digest._reconcile_card_events(events, [], data, None, seen, []), [])
        self.assertIn(events[0]['fingerprint'], seen)

    def test_inbox_and_card_comment_emit_one_event_with_both_identities(self):
        source = record()
        data = snapshot([])
        data['card_activity'] = [source]
        inbox = {'task_title': 'Checkout', 'task_url': URL, 'kind': 'comment', 'details': 'Aleksei Gruzdev написал: схема покупки готова.', 'occurred_at': '2026-10-08', 'confidence': 1}
        data['updates'] = [inbox]
        events = activity.activity_events(data, None, set(), date(2026, 10, 8))
        incoming = digest.update_events(data, set())
        merged = digest._reconcile_card_events(events, incoming, data, None, set(), [])
        self.assertEqual(len(merged), 1)
        self.assertIn(incoming[0]['fingerprint'], merged[0]['alias_fingerprints'])

    def test_inbox_paraphrase_does_not_repeat_a_known_native_comment(self):
        source = record(author='Ilmira Akhmetkhanova')
        data = snapshot([])
        data['card_activity'] = [source]
        inbox = {'task_title': 'Checkout', 'task_url': URL, 'kind': 'comment', 'details': 'Ilmira Akhmetkhanova поблагодарила за схему.', 'occurred_at': '2026-10-08', 'confidence': 1}
        incoming = digest.update_events({'updates': [inbox]}, set())
        seen = set()
        self.assertEqual(digest._reconcile_card_events([], incoming, data, None, seen, [source]), [])
        self.assertIn(incoming[0]['fingerprint'], seen)

    def test_new_second_comment_is_not_discarded_by_old_same_day_inbox(self):
        source = record()
        current = copy.deepcopy(source)
        current['history'][0]['items'].append({'url': URL + '?d=thread1', 'text': 'Aleksei Gruzdev\nТехническая команда приняла результат.'})
        data = snapshot([])
        data['card_activity'] = [current]
        old = {'task_title': 'Checkout', 'task_url': URL, 'kind': 'comment', 'details': 'Aleksei Gruzdev написал: схема готова.', 'occurred_at': '2026-10-08', 'confidence': 1}
        data['updates'] = [old]
        seen = {digest._update_fingerprint(old)}
        events = activity.activity_events(data, {'card_activity': [source]}, seen, date(2026, 10, 8))
        merged = digest._reconcile_card_events(events, [], data, None, seen, [source])
        self.assertEqual(len(merged), 1)
        self.assertIn('приняла результат', merged[0]['details'])

    def test_failed_card_keeps_good_baseline_in_no_send_run(self):
        before = record()
        failed = {**record(), 'content_complete': False, 'comments_complete': False, 'updates_complete': False, 'errors': ['Timeout']}
        board = snapshot([task('Checkout', 'In Progress', url=URL)], captured_at=NOW.isoformat())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous_path = root / 'previous.json'
            previous_path.write_text(json.dumps(board))
            state_path = root / 'state.json'
            state_path.write_text(json.dumps({'last_snapshot': str(previous_path), 'card_baselines': [before]}))
            with patch.multiple(digest, STATE_FILE=state_path, RUNS_DIR=root/'runs', SNAPSHOTS_DIR=root/'snapshots', REPORTS_DIR=root/'reports'), patch.object(digest, '_now', return_value=NOW), patch.object(digest, 'capture_sources', return_value={}), patch.object(digest, 'extract_snapshot', return_value=copy.deepcopy(board)), patch.object(activity, 'capture_card_activity', return_value=[failed]), patch.object(digest, 'weather_line', return_value=None), patch.object(digest, 'send_telegram') as send:
                result = digest.run_digest(send=False)
            state = json.loads(state_path.read_text())
            self.assertEqual(state['card_baselines'], [before])
            self.assertFalse(result['sent'])
            send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
