"""Portable checks for the Android controller; native/Keystore run on device."""
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cashminer.platform import android_runtime as android
from cashminer.mining.bridge import MiningSettings


def config(**changes):
    values=dict(network='testnet3',reward_address='',mode='pool',
                pool_url='stratum+tcp://127.0.0.1:3333',pool_user='test',
                cpu_percent=25,gpu_percent=0)
    values.update(changes)
    return MiningSettings(**values)


class AndroidControllerTests(unittest.TestCase):
    def test_activity_recreation_reuses_the_existing_app_and_sessions(self):
        service=SimpleNamespace(close_event=threading.Event())
        with patch.object(android,'_service',service),\
             patch.object(android,'_server',SimpleNamespace(server_port=12345)),\
             patch.object(android,'_java'):
            self.assertEqual(android.start_app(None),'http://127.0.0.1:12345/')
            self.assertIs(android._service,service)

    def controller(self):
        lines=[];exits=[]
        return android.AndroidMinerController(lines.append,lambda *args:exits.append(args)),lines,exits

    def test_rejects_unsupported_resources_before_starting_service(self):
        with patch.object(android,'_gateway') as gateway:
            for changes in ({'cpu_percent':0,'gpu_percent':25},{'cpu_percent':101},
                            {'gpu_percent':25},{'gpu_overrides':{0:25}}):
                with self.subTest(changes=changes):
                    control,_,_=self.controller()
                    with self.assertRaises(ValueError):control.start(config(**changes))
            gateway.start.assert_not_called()

    def test_100_percent_is_passed_to_native_service_without_an_android_cap(self):
        control,_,_=self.controller()
        with patch.object(android,'native_libraries',return_value=['libbch_hashscan.so']),patch.object(android,'_gateway') as gateway:
            gateway.poll.return_value=json.dumps({'type':'exit','code':0,'forced':False})
            control.start(config(cpu_percent=100));control.wait_for_log_close(2)
            self.assertEqual(json.loads(gateway.start.call_args.args[2])['cpu_percent'],100)
            self.assertFalse(control.running())

    def test_requires_packaged_native_library(self):
        control,_,_=self.controller()
        with patch.object(android,'native_libraries',return_value=[]):
            with self.assertRaises(RuntimeError):control.start(config())
        self.assertFalse(control.running())

    def test_forwards_lines_and_service_exit_and_serializes_configuration(self):
        control,lines,exits=self.controller()
        with patch.object(android,'native_libraries',return_value=['libbch_hashscan.so']),patch.object(android,'_gateway') as gateway:
            gateway.poll.side_effect=[json.dumps({'type':'line','line':'work ready'}),
                                      json.dumps({'type':'exit','code':0,'forced':False})]
            control.start(config());control.wait_for_log_close(2)
            self.assertFalse(control.running());self.assertEqual(lines,['work ready'])
            self.assertEqual(exits,[(0,None,False)])
            net,run,payload=gateway.start.call_args.args
            self.assertEqual(net,'testnet3');self.assertEqual(json.loads(payload)['run_id'],run)
            self.assertEqual(json.loads(payload)['cpu_percent'],25)

    def test_failed_android_service_start_does_not_mark_controller_running(self):
        control,_,_=self.controller()
        with patch.object(android,'native_libraries',return_value=['libbch_hashscan.so']),patch.object(android,'_gateway') as gateway:
            gateway.start.side_effect=RuntimeError('service unavailable')
            with self.assertRaises(RuntimeError):control.start(config())
        self.assertFalse(control.running())

    def test_log_pipe_preserves_lines_across_fragmented_writes(self):
        with patch.object(android,'_gateway') as sink:
            stream=android._Pipe(sink);stream.write('first');stream.write(' line\r\nsecond\n')
            self.assertEqual([c.args[0] for c in sink.emitLine.call_args_list],['first line','second'])

    def test_stop_sends_run_identity_and_retains_stop_reason(self):
        control,_,_=self.controller();control._network='testnet3';control._run='run';control._done.clear()
        with patch.object(android,'_gateway') as gateway:
            gateway.stop.side_effect=lambda *args:control._done.set()
            self.assertTrue(control.request_stop('app_close'));control.stop()
            gateway.stop.assert_called_once_with('testnet3','run')
            self.assertEqual(control._reason,'app_close')


if __name__=='__main__':unittest.main()
