"""Restart regressions: temporary storage, no browser/network/Telegram writes."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import sp9_activity as activity
import sp9_digest as digest
from test_sp9_digest import task, snapshot, TZ

NOW = datetime(2026, 10, 14, 11, 0, tzinfo=TZ)
SINCE = date(2026, 10, 13)
KEYS = ['a' * 32, 'b' * 32]
TASKS = [task('First', 'To Do', url='https://app.notion.com/p/' + KEYS[0]),
         task('Second', 'To Do', url='https://app.notion.com/p/' + KEYS[1])]


def complete(index=0):
    return {'title': TASKS[index]['title'], 'url': TASKS[index]['url'],
            'captured_at': NOW.isoformat(), 'identity_verified': True,
            **{k: True for k in activity.COMPLETE_FLAGS},
            'content': [{'id': 'block', 'text': 'Brief', 'links': []}],
            'comments': [], 'history': [], 'errors': [],
            'task_scope': activity._task_scope(TASKS[index]),
            'capture_scope': activity._capture_scope(SINCE)}


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.multiple(digest, STATE_FILE=self.root/'state.json',
            RUNS_DIR=self.root/'runs', SNAPSHOTS_DIR=self.root/'snapshots', REPORTS_DIR=self.root/'reports'))
        self.stack.enter_context(patch.object(digest, '_now', return_value=NOW))
        clock = self.stack.enter_context(patch.object(activity, 'datetime', wraps=datetime))
        clock.now.return_value = NOW
        previous = snapshot(TASKS, captured_at='2026-10-13T12:00:00+03:00')
        previous_path = self.root/'previous.json'
        digest._atomic_json(previous_path, previous)
        digest._atomic_json(digest.STATE_FILE, {**digest._default_state(), 'last_snapshot': str(previous_path)})
        self.capture = self.stack.enter_context(patch.object(digest, 'capture_sources', return_value={}))
        board = snapshot(TASKS, captured_at=NOW.isoformat())
        self.extract = self.stack.enter_context(patch.object(digest, 'extract_snapshot', side_effect=lambda *args: copy.deepcopy(board)))
        self.stack.enter_context(patch.object(activity.capture, '_playwright', return_value=MagicMock()))
        self.launch = self.stack.enter_context(patch.object(activity.capture, '_launch_context', return_value=MagicMock()))
        self.read = self.stack.enter_context(patch.object(activity, '_capture_card', side_effect=[complete(0), complete(1)]))
        self.edit = self.stack.enter_context(patch.object(digest, 'prepare_editorial_digest', return_value='Verified release'))
        self.stack.enter_context(patch.object(digest, 'weather_line', return_value=None))
        self.send = self.stack.enter_context(patch.object(digest, 'send_telegram', return_value=42))

    def state(self):
        return digest._load_json(digest.STATE_FILE, {})

    def test_restart_reads_only_missing_card_and_preserves_capture_time(self):
        self.read.side_effect = [complete(0), KeyboardInterrupt('restart')]
        with self.assertRaises(KeyboardInterrupt):
            digest.run_digest(send=False)
        first_state = self.state()
        run = Path(first_state['collection_run']['path'])
        self.assertTrue((run/'cards'/f'{KEYS[0]}.json').exists())
        self.assertEqual(first_state['last_snapshot'], str(self.root/'previous.json'))
        self.read.reset_mock(side_effect=True)
        self.read.side_effect = [complete(1)]
        result = digest.run_digest(send=False)
        self.read.assert_called_once()
        self.assertEqual(self.read.call_args.args[1]['url'], TASKS[1]['url'])
        self.capture.assert_called_once()
        self.extract.assert_called_once()
        current = json.loads(Path(result['snapshot']).read_text())
        self.assertEqual(current['activity_coverage']['content'], 2)
        self.assertEqual(current['card_activity'][0]['captured_at'], NOW.isoformat())
        self.assertTrue(current['collection_resume']['resumed'])
        self.assertIsNone(self.state()['collection_run'])
        self.send.assert_not_called()
        self.assertTrue(self.launch.call_args.kwargs['headless'])

    def test_editor_failure_keeps_baseline_and_reuses_all_reads(self):
        self.edit.side_effect = [RuntimeError('editor failed'), 'Verified release']
        with self.assertRaisesRegex(RuntimeError, 'editor failed'):
            digest.run_digest(send=False)
        self.assertEqual(self.state()['last_snapshot'], str(self.root/'previous.json'))
        self.assertIsNotNone(self.state()['collection_run'])
        digest.run_digest(send=False)
        self.assertEqual(self.read.call_count, 2)
        self.launch.assert_called_once()
        self.capture.assert_called_once()
        self.extract.assert_called_once()

    def test_snapshot_checkpoint_corruption_repeats_extraction(self):
        self.read.side_effect = [KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            digest.run_digest(send=False)
        run = Path(self.state()['collection_run']['path'])
        (run/'collection_snapshot.json').write_text('{broken')
        self.read.side_effect = [complete(0), complete(1)]
        digest.run_digest(send=False)
        self.assertEqual(self.extract.call_count, 2)

    def test_interrupted_extraction_uses_saved_images(self):
        manifest = {'captured_at': NOW.isoformat(), 'board_url': digest.BOARD_URL,
                    'motion_url': activity.capture.MOTION_URL}
        def capture(run, **kwargs):
            for key in ('board_images', 'updates_images', 'motion_images'):
                file = run/(key+'.jpg')
                file.write_bytes(b'fixture')
                manifest[key] = [str(file)]
            digest._atomic_json(run/'capture_manifest.json', manifest)
            return manifest
        self.capture.side_effect = capture
        self.extract.side_effect = [KeyboardInterrupt(), snapshot(TASKS, captured_at=NOW.isoformat())]
        with self.assertRaises(KeyboardInterrupt):
            digest.run_digest(send=False)
        digest.run_digest(send=False)
        self.capture.assert_called_once()
        self.assertEqual(self.extract.call_count, 2)

    def test_bad_image_manifest_is_recaptured(self):
        run, _ = digest._collection_dir(self.state(), NOW, SINCE)
        digest._atomic_json(run/'capture_manifest.json', {
            'captured_at': NOW.isoformat(), 'board_url': digest.BOARD_URL,
            'motion_url': activity.capture.MOTION_URL, 'board_images': [str(self.root/'missing.jpg')],
            'updates_images': [], 'motion_images': []})
        digest._collection_snapshot(run, NOW, headless=True)
        self.capture.assert_called_once()

    def test_failed_validation_recaptures_images_and_keeps_each_extraction(self):
        def fresh_capture(run, **kwargs):
            manifest = {'captured_at': NOW.isoformat(), 'board_url': digest.BOARD_URL,
                        'motion_url': activity.capture.MOTION_URL}
            for key in ('board_images', 'updates_images', 'motion_images'):
                image = run/(key+'.jpg')
                image.write_bytes(b'original pixels' if self.capture.call_count==1 else b'fresh pixels')
                manifest[key] = [str(image)]
            digest._atomic_json(run/'capture_manifest.json', manifest)
            return manifest
        self.capture.side_effect = fresh_capture
        invalid = snapshot(TASKS[:1], captured_at=NOW.isoformat())
        invalid['board_counts']['to_do'] = 2
        def extract(manifest, destination):
            (destination/'codex.log').write_text('attempt '+str(self.extract.call_count))
            return copy.deepcopy(invalid if self.extract.call_count==1 else snapshot(TASKS, captured_at=NOW.isoformat()))
        self.extract.side_effect = extract
        with self.assertRaisesRegex(RuntimeError, 'Неполный снимок'):
            digest.run_digest(send=False)
        run = Path(self.state()['collection_run']['path'])
        digest.run_digest(send=False)
        self.assertEqual(self.capture.call_count, 2)
        self.assertTrue((run/'extractions'/'01'/'codex.log').exists())
        self.assertTrue((run/'extractions'/'02'/'codex.log').exists())
        saved = list((run/'rejected_sources').glob('*/board_images.jpg'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), b'original pixels')

    def test_expired_day_period_profile_or_baseline_starts_new_run(self):
        for change in ('age', 'day', 'since', 'baseline', 'profile', 'outside'):
            with self.subTest(change=change):
                state = self.state()
                state['collection_run'] = None
                run, _ = digest._collection_dir(state, NOW, SINCE)
                when, since = NOW, SINCE
                if change == 'age': when += timedelta(hours=2, seconds=1)
                if change == 'day': when += timedelta(days=1)
                if change == 'since': since -= timedelta(days=1)
                if change == 'baseline': state['last_snapshot'] = 'changed'
                if change == 'profile': state['collection_run']['scope']['profile'] = 'other'
                if change == 'outside': state['collection_run']['path'] = str(self.root)
                other, resumed = digest._collection_dir(state, when, since)
                self.assertFalse(resumed)
                self.assertNotEqual(run, other)

    def test_structured_source_failure_before_validation_refreshes_source(self):
        def fresh_capture(run, **kwargs):
            manifest = {'captured_at': NOW.isoformat(), 'board_url': digest.BOARD_URL,
                        'motion_url': activity.capture.MOTION_URL}
            for key in ('board_images', 'updates_images', 'motion_images'):
                image = run/(key+'.jpg')
                image.write_bytes(b'pixels')
                manifest[key] = [str(image)]
            digest._atomic_json(run/'capture_manifest.json', manifest)
            return manifest
        self.capture.side_effect = fresh_capture
        self.extract.side_effect = [digest.SnapshotValidationError('Неверный JSON'),
                                   snapshot(TASKS, captured_at=NOW.isoformat())]
        with self.assertRaisesRegex(digest.SnapshotValidationError, 'Неверный JSON'):
            digest.run_digest(send=False)
        run = Path(self.state()['collection_run']['path'])
        self.assertTrue((run/'capture_rejected.json').exists())
        self.send.assert_not_called()
        self.assertEqual(self.state()['last_snapshot'], str(self.root/'previous.json'))
        digest.run_digest(send=False)
        self.assertEqual(self.capture.call_count, 2)
        self.assertEqual(len(list((run/'rejected_sources').glob('*/capture_rejected.json'))), 1)

    def test_cli_failure_preserves_valid_images_for_retry(self):
        run, _ = digest._collection_dir(self.state(), NOW, SINCE)
        manifest = {'captured_at': NOW.isoformat(), 'board_url': digest.BOARD_URL,
                    'motion_url': activity.capture.MOTION_URL}
        for key in ('board_images', 'updates_images', 'motion_images'):
            image = run/(key+'.jpg')
            image.write_bytes(b'pixels')
            manifest[key] = [str(image)]
        digest._atomic_json(run/'capture_manifest.json', manifest)
        self.extract.side_effect = [RuntimeError('Codex недоступен'),
                                   snapshot(TASKS, captured_at=NOW.isoformat())]
        with self.assertRaisesRegex(RuntimeError, 'Codex недоступен'):
            digest._collection_snapshot(run, NOW, headless=True)
        self.assertFalse((run/'capture_rejected.json').exists())
        digest._collection_snapshot(run, NOW, headless=True)
        self.capture.assert_not_called()

    def test_malformed_partial_old_future_or_wrong_card_is_not_reused(self):
        path = self.root/'card.json'
        for change in ('partial', 'old', 'future', 'day', 'id', 'scope', 'identity', 'corrupt', 'shape'):
            with self.subTest(change=change):
                record = complete()
                if change == 'partial': record['comments_complete'] = False
                if change == 'old': record['captured_at'] = (NOW-timedelta(hours=2, seconds=1)).isoformat()
                if change == 'future': record['captured_at'] = (NOW+timedelta(minutes=1)).isoformat()
                if change == 'day': record['captured_at'] = (NOW-timedelta(days=1)).isoformat()
                if change == 'id': record['url'] = TASKS[1]['url']
                if change == 'scope': record['capture_scope']['since'] = '2026-10-12'
                if change == 'identity': record['identity_verified'] = False
                if change == 'shape': record['history'] = None
                path.write_text('{bad' if change == 'corrupt' else json.dumps(record))
                self.assertIsNone(activity._resume_card(path, TASKS[0], SINCE, NOW))

    def test_partial_card_is_reread_and_old_attempts_are_preserved(self):
        destination = self.root/'cards'
        destination.mkdir()
        partial = {**complete(), 'comments_complete': False, 'errors': ['Timeout']}
        activity._save_card_attempt(destination, KEYS[0], partial, partial, SINCE)
        records = activity.capture_card_activity(TASKS[:1], destination, since=SINCE)
        self.read.assert_called_once()
        self.assertTrue(records[0]['comments_complete'])
        self.assertEqual(len(records[0]['attempts']), 2)
        self.assertTrue((destination/'attempts'/KEYS[0]/'01.json').exists())
        self.assertTrue((destination/'attempts'/KEYS[0]/'02.json').exists())

    def test_changed_board_properties_invalidate_cached_card_but_ocr_title_does_not(self):
        path = self.root/'card.json'
        activity._atomic_record(path, complete())
        changed = copy.deepcopy(TASKS[0])
        changed['title'] = 'Different OCR spelling'
        self.assertIsNotNone(activity._resume_card(path, changed, SINCE, NOW))
        for field, value in [('status', 'Review'), ('due_date', '2026-10-15'), ('assignees', ['New person'])]:
            with self.subTest(field=field):
                changed = {**TASKS[0], field: value}
                self.assertIsNone(activity._resume_card(path, changed, SINCE, NOW))

    def test_atomic_write_interruption_does_not_destroy_last_complete_card(self):
        path = self.root/'card.json'
        activity._atomic_record(path, complete())
        with patch.object(activity.os, 'fsync', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                activity._atomic_record(path, {'incomplete': True})
        self.assertEqual(json.loads(path.read_text()), complete())

    def test_delivery_failure_resumes_without_collecting_or_repeating_sent_part(self):
        self.send.side_effect = [RuntimeError('offline'), 42]
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            digest.run_digest(send=True)
        self.assertIsNone(self.state()['collection_run'])
        self.assertIsNotNone(self.state()['delivery_batch'])
        result = digest.run_digest(send=True)
        self.assertTrue(result['sent'])
        self.capture.assert_called_once()
        self.extract.assert_called_once()
        self.assertEqual(self.read.call_count, 2)

    def test_interruption_while_waiting_keeps_prepared_delivery_and_send_time(self):
        with patch.object(digest.time, 'sleep', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                digest.run_digest(send=True, send_at='11:50')
        batch = self.state()['delivery_batch']
        self.assertEqual(batch['send_after'], '2026-10-14T11:50:00+03:00')
        self.send.assert_not_called()
        with patch.object(digest, '_now', return_value=NOW.replace(hour=12)):
            result = digest.run_digest(send=True)
        self.assertTrue(result['sent'])
        self.send.assert_called_once()
        self.capture.assert_called_once()

    def test_already_delivered_today_skips_collection(self):
        state = self.state()
        state.update(last_successful_send=NOW.isoformat(), last_successful_digest_date='2026-10-14')
        digest._atomic_json(digest.STATE_FILE, state)
        result = digest.run_digest(send=True, skip_if_sent_today=True)
        self.assertEqual(result['reason'], 'already_sent_today')
        self.capture.assert_not_called()
        self.send.assert_not_called()

    def test_no_send_preserves_published_summary_despite_new_snapshot(self):
        state = self.state()
        state.update(last_successful_send='2026-10-13T12:01:00+03:00',
                     last_successful_digest_date='2026-10-13')
        digest._atomic_json(digest.STATE_FILE, state)
        result = digest.run_digest(send=False)
        saved = self.state()
        self.assertNotEqual(saved['last_snapshot'], state['last_snapshot'])
        self.assertEqual(saved['last_published_summary']['release_date'], '2026-10-13')
        self.assertEqual(digest._published_summary(saved), saved['last_published_summary'])
        current = digest._load_json(Path(result['snapshot']), {})
        self.assertEqual(current['previous_published_metrics'], saved['last_published_summary']['metrics'])
        self.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
