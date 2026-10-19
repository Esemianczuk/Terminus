import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('collector', Path(__file__).parents[1] / 'agents' / 'collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def event(n):
    return {'id': str(n), 'kind': 'context', 'context': 'test', 'device_id': 'test-device', 'intensity': .5, 'source': 'manual'}


def test_collector_can_only_connect_to_local_core():
    assert collector.normalized_url('http://127.0.0.1:8769/') == 'http://127.0.0.1:8769'
    for url in ['http://192.168.1.20:8769', 'https://pet.example.test', 'https://user:secret@example.test', 'https://example.test?token=secret', 'file:///tmp/core']:
        with pytest.raises(ValueError):
            collector.normalized_url(url)


def test_outbox_refuses_remote_destination_before_reading_events(tmp_path):
    queue = collector.Outbox(tmp_path / 'outbox.db')
    queue.add(event(1))
    with patch.object(collector.urllib.request, 'urlopen') as send:
        with pytest.raises(ValueError):
            queue.flush('https://pet.example.test', 'local-token')
        send.assert_not_called()


def test_outbox_is_bounded_deduplicated_and_replayed(tmp_path):
    queue = collector.Outbox(tmp_path / 'outbox.db')
    for n in range(300):
        queue.add(event(n))
    queue.add(event(299))
    assert queue.count() == 256
    with patch.object(collector.urllib.request, 'urlopen', side_effect=OSError('offline')):
        assert queue.flush('http://127.0.0.1:8769', 'test-token') == 0
    assert queue.count() == 256
    delivered = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"accepted": true, "revision": 1}'

    def success(req, timeout):
        delivered.append(json.loads(req.data))
        return Response()

    with patch.object(collector.urllib.request, 'urlopen', side_effect=success):
        assert queue.flush('http://127.0.0.1:8769', 'test-token') == 256
    assert len({e['id'] for e in delivered}) == 256
    assert all(isinstance(e['timestamp'], (int, float)) for e in delivered)
    assert queue.count() == 0


def test_legacy_outbox_replays_original_observation_time(tmp_path):
    queue = collector.Outbox(tmp_path / 'outbox.db')
    payload = event(7)
    with patch.object(collector.time, 'time', return_value=100):
        queue.db.execute('INSERT INTO outbox VALUES (?, ?, ?)', (payload['id'], 7, json.dumps(payload)))
        queue.db.commit()

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return b'{"accepted":true}'

        def delivered(req, timeout):
            assert json.loads(req.data)['timestamp'] == 7
            return Response()

        with patch.object(collector.urllib.request, 'urlopen', side_effect=delivered):
            assert queue.flush('http://127.0.0.1:8769', 'test-token') == 1
    assert queue.count() == 0
    assert not (tmp_path / 'outbox.db').stat().st_mode & 0o077


def test_expired_events_are_not_replayed(tmp_path):
    queue = collector.Outbox(tmp_path / 'outbox.db')
    with patch.object(collector.time, 'time', return_value=1):
        queue.add(event(1))
    with patch.object(collector.urllib.request, 'urlopen') as send:
        assert queue.flush('http://127.0.0.1:8769', 'test-token') == 0
        send.assert_not_called()
    assert queue.count() == 0
