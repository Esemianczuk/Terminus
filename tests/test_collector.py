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


def test_remote_token_transport_requires_https():
    assert collector.normalized_url('http://127.0.0.1:8769/') == 'http://127.0.0.1:8769'
    assert collector.normalized_url('https://pet.example.test') == 'https://pet.example.test'
    for url in ['http://192.168.1.20:8769', 'https://user:secret@example.test', 'https://example.test?token=secret', 'file:///tmp/core']:
        with pytest.raises(ValueError):
            collector.normalized_url(url)


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
