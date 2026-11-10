"""Regresión de logs observacionales: los hechos no son un veredicto."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ENGINE = Path(__file__).resolve().parents[1] / 'mining_engine'
sys.path.insert(0, str(ENGINE))
from fablous import observer as obs
from fablous import headers as p2p

PARENT = 'ab' * 32
OUR = 'cd' * 32
PEER1 = '1.1.1.1:48335'
PEER2 = '2.2.2.2:48335'


class TestObservationalLogs(unittest.TestCase):
    def fake(self, peer, parent):
        self.assertEqual(parent, PARENT)
        return {'peer': peer, 'status': 'response', 'stage': 'completed',
                'locator_parent': parent, 'response_headers': 1,
                'headers': [{'hash': OUR if peer == PEER1 else 'ef' * 32,
                             'prev_hash': parent, 'nBits': '1d00ffff',
                             'ntime': 1000, 'nonce': 9}], 'error': None}

    def test_independent_peer_results_disagree_without_aggregated_verdict(self):
        results = obs.observe_peers([PEER1, PEER2], PARENT, observer=self.fake)
        self.assertEqual({r['peer'] for r in results}, {PEER1, PEER2})
        self.assertEqual({r['headers'][0]['hash'] for r in results}, {OUR, 'ef' * 32})
        lines = '\n'.join(x for r in results for x in obs.format_peer_observation(r))
        self.assertIn(OUR, lines)
        self.assertIn('ef' * 32, lines)
        self.assertNotIn('accepted=', lines)
        self.assertNotIn('aceptaron=', lines)

    def test_empty_headers_are_not_labeled_as_rejection(self):
        result = {'peer': PEER1, 'status': 'response', 'stage': 'completed',
                  'locator_parent': PARENT, 'response_headers': 0, 'headers': [], 'error': None}
        text = '\n'.join(obs.format_peer_observation(result))
        self.assertIn('headers_count=0', text)
        self.assertNotIn('rechaz', text.lower())
        self.assertNotIn('accepted', text.lower())

    def test_failed_peer_cannot_be_counted_as_agreement(self):
        def faulty(peer, parent):
            if peer == PEER2:
                raise TimeoutError('no headers')
            return self.fake(peer, parent)
        results = obs.observe_peers([PEER1, PEER2], PARENT, observer=faulty)
        self.assertEqual(len(results), 2)
        err = next(r for r in results if r['peer'] == PEER2)
        self.assertEqual(err['status'], 'error')
        self.assertIsNone(err['response_headers'])
        self.assertIn('TimeoutError', err['error'])

    def test_peers_deduplicated(self):
        results = obs.observe_peers([PEER1, PEER1], PARENT, observer=self.fake)
        self.assertEqual(len(results), 1)

    def test_getheaders_uses_parent_locator_and_records_zero_response(self):
        fake_socket = mock.Mock()
        with (mock.patch.object(obs, 'BlockBroadcaster') as broad_cls,
              mock.patch.object(obs, 'read_message', return_value=('headers', b'\x00')),
              mock.patch.object(obs, '_getheaders_payload', wraps=p2p._getheaders_payload) as payload):
            broad_cls.return_value.connect.return_value = fake_socket
            result = obs.probe_peer_headers(PEER1, PARENT, timeout=1)
            payload.assert_called_once_with([PARENT])
        self.assertEqual(result['status'], 'response')
        self.assertEqual(result['response_headers'], 0)
        self.assertEqual(result['headers'], [])
        self.assertIsNone(result['error'])

    def test_probe_error_is_not_silenced(self):
        with mock.patch.object(obs, 'BlockBroadcaster') as broadcaster:
            broadcaster.return_value.connect.side_effect = TimeoutError('conexión agotada')
            result = obs.probe_peer_headers(PEER1, PARENT)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['stage'], 'connect')
        self.assertIn('TimeoutError', result['error'])

    def test_observer_module_does_not_mutate_header_cache(self):
        client = p2p.TempnetHeaderClient(peers=[])
        old_chain = client.chain
        old_work = client.work
        obs.observe_peers([PEER1], PARENT, observer=self.fake)
        self.assertIs(client.chain, old_chain)
        self.assertEqual(client.work, old_work)


if __name__ == '__main__':
    unittest.main()
