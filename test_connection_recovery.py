"""Offline regression checks; extracts real UI methods without requiring Qt."""
import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor
import studio_monitor_backend as backend
from selftest import MockRadioBOSS
from http.server import ThreadingHTTPServer
import threading

source=ast.parse(Path(__file__).with_name('StudioMonitorNative.py').read_text(encoding='utf-8'))
cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='StudioMonitor')
methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in
         ('mark_stale','apply_state','watchdog_tick','request_state')]
namespace={'time':time,'GREEN':'green','RED':'red','AMBER':'amber','ACTIVE_BG':'black',
           'ALERT_BG':'black','backend':backend,'ThreadPoolExecutor':ThreadPoolExecutor}
exec(compile(ast.Module(body=methods,type_ignores=[]),'<UI methods>','exec'),namespace)

class RecoveryTests(unittest.TestCase):
    def monitor(self):
        m=SimpleNamespace(_config_generation=0,_request_serial=3,_last_success=100.,
            _last_success_text='2026-09-04 23:47:40',_last_poll_error='',busy=False,
            _weather_busy=False,_request_started=0.,_radioboss_playing=True,
            _silence_started=1.,_pool_generation=0)
        for name in ('onair_lbl','conn','rb_state','system','api_error','last_update',
                     'turntable','remaining','next_in','api_info','sys_state','bridge_state',
                     'cur_artist','cur_title','cur_album','bpm','listeners','playstate',
                     'progress','next_artist','next_title','next_album','timer'):
            setattr(m,name,Mock())
        m.timer.interval.return_value=1500
        m._set_silence_indicator=Mock()
        m.mark_stale=lambda msg: namespace['mark_stale'](m,msg)
        return m

    def test_error_invalidates_green_status_and_keeps_success_time(self):
        m=self.monitor()
        namespace['apply_state'](m,dict(_generation=0,_serial=3,connected=False,error='sendall'))
        m.onair_lbl.setText.assert_called_with('DATA STALE')
        self.assertEqual(m._last_success,100.)
        self.assertFalse(m._radioboss_playing)
        self.assertEqual(m._last_poll_error,'sendall')

    def test_late_reply_cannot_restore_connected(self):
        m=self.monitor()
        namespace['apply_state'](m,dict(_generation=0,_serial=2,connected=True))
        m.onair_lbl.setText.assert_not_called()
        self.assertEqual(m._last_success,100.)

    def test_fresh_reply_restores_status(self):
        m=self.monitor()
        # Stop at the first title widget, after the full connection status block.
        m.cur_artist.setText.side_effect=StopIteration
        with self.assertRaises(StopIteration):
            namespace['apply_state'](m,dict(_generation=0,_serial=3,connected=True))
        m.onair_lbl.setText.assert_called_with('ON AIR')
        self.assertGreater(m._last_success,100.)
        self.assertEqual(m._last_poll_error,'')

    def test_watchdog_detects_stale_data_even_when_worker_is_not_busy(self):
        m=self.monitor()
        namespace['watchdog_tick'](m)
        m.conn.setText.assert_called_with('● RECONNECTING')

    def test_worker_exception_emits_failed_state_and_allows_retry(self):
        m=self.monitor();m.signals=SimpleNamespace(state=Mock())
        m.pool=SimpleNamespace(submit=lambda job:job())
        with patch.object(backend,'load_config',side_effect=RuntimeError('test')):
            namespace['request_state'](m)
        data=m.signals.state.emit.call_args.args[0]
        self.assertFalse(data['connected']);self.assertEqual(data['_serial'],4)
        self.assertFalse(m.busy)

    def test_concurrent_http_calls_and_recovery_after_transport_failure(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),MockRadioBOSS)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        cfg={'radioboss_host':'127.0.0.1','radioboss_port':server.server_port,
             'radioboss_password':'test-secret'}
        try:
            with patch.object(backend.urllib.request,'build_opener',side_effect=AttributeError("'NoneType' object has no attribute 'sendall'")):
                self.assertFalse(backend.rb_state(cfg)['connected'])
            with ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(lambda _:backend.rb_state(cfg),range(20)))
            self.assertTrue(all(x['connected'] for x in results),results)
        finally:
            server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
