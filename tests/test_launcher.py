import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

import launcher


class LauncherTests(unittest.TestCase):
    def response(self, value):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(json.dumps(value).encode()))
        response.__exit__ = Mock(return_value=False)
        return response

    def test_online_console_is_reused(self):
        with patch('launcher._probe_console', return_value=True), patch('launcher._spawn_console') as spawn:
            self.assertEqual(launcher.ensure_console(), launcher.CONSOLE_URL)
            spawn.assert_not_called()

    def test_offline_console_is_started_hidden_and_reused_when_ready(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
             patch('launcher.DATA_DIR', Path(directory)), \
             patch('launcher._probe_console', side_effect=[False, False, True]), \
             patch('launcher.subprocess.Popen', return_value=process) as spawn, \
             patch('launcher.time.sleep'):
            self.assertEqual(launcher.ensure_console(), launcher.CONSOLE_URL)
            command = spawn.call_args.args[0]
            self.assertEqual(command, [sys.executable, str(launcher.SERVER_PATH)])
            self.assertTrue(Path(command[1]).is_absolute())
            if os.name == 'nt':
                self.assertEqual(spawn.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            self.assertTrue((Path(directory) / 'launcher.log').exists())

    def test_health_service_identity_must_match(self):
        with patch('launcher.urlopen', return_value=self.response({'service': 'unrelated'})), \
             patch('launcher._spawn_console') as spawn:
            with self.assertRaisesRegex(launcher.LauncherError, '其他服务'):
                launcher.ensure_console()
            spawn.assert_not_called()

    def test_transient_timeout_during_owned_child_start_is_retried(self):
        failure = launcher.LauncherError('starting')
        failure.__cause__ = URLError(TimeoutError('timed out'))
        process = Mock()
        process.poll.return_value = None
        with patch('launcher._probe_console', side_effect=[False, failure, True]), \
             patch('launcher._spawn_console', return_value=process) as spawn, \
             patch('launcher.time.sleep'):
            self.assertEqual(launcher.ensure_console(), launcher.CONSOLE_URL)
            spawn.assert_called_once()

    def test_health_json_for_this_service_is_accepted(self):
        with patch('launcher.urlopen', return_value=self.response({'service': launcher.SERVICE_NAME})):
            self.assertTrue(launcher._probe_console())

    def test_refused_connection_means_offline(self):
        failure = URLError(ConnectionRefusedError(errno.ECONNREFUSED, 'refused'))
        with patch('launcher.urlopen', side_effect=failure):
            self.assertFalse(launcher._probe_console())

    def test_timed_out_connection_with_exclusively_free_port_starts_console(self):
        failure = URLError(TimeoutError('timed out'))
        with patch('launcher.urlopen', side_effect=[failure, self.response({'service': launcher.SERVICE_NAME})]), \
             patch('launcher._port_is_free', return_value=True) as free_port, \
             patch('launcher._spawn_console') as spawn:
            self.assertEqual(launcher.ensure_console(), launcher.CONSOLE_URL)
            free_port.assert_called_once_with()
            spawn.assert_called_once_with()

    def test_timed_out_connection_with_occupied_port_never_starts_console(self):
        failure = URLError(TimeoutError('timed out'))
        with patch('launcher.urlopen', side_effect=failure), \
             patch('launcher._port_is_free', return_value=False), \
             patch('launcher._spawn_console') as spawn:
            with self.assertRaises(launcher.LauncherError):
                launcher.ensure_console()
            spawn.assert_not_called()

    def test_response_timeout_requires_proof_that_port_is_free(self):
        for available in (True, False):
            with self.subTest(available=available), \
                 patch('launcher.urlopen', side_effect=TimeoutError('timed out')), \
                 patch('launcher._port_is_free', return_value=available):
                if available:
                    self.assertFalse(launcher._probe_console())
                else:
                    with self.assertRaises(launcher.LauncherError):
                        launcher._probe_console()

    def test_port_check_uses_exclusive_binding_on_windows(self):
        probe = MagicMock()
        probe.__enter__.return_value = probe
        with patch('launcher.socket.socket', return_value=probe):
            self.assertTrue(launcher._port_is_free())
        probe.bind.assert_called_once_with(('127.0.0.1', 8765))
        if os.name == 'nt':
            probe.setsockopt.assert_called_once_with(launcher.socket.SOL_SOCKET, launcher.socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.__exit__.assert_called_once()

    def test_port_check_failure_is_not_reported_as_free(self):
        probe = MagicMock()
        probe.__enter__.return_value = probe
        probe.bind.side_effect = OSError(errno.EADDRINUSE, 'address already in use')
        with patch('launcher.socket.socket', return_value=probe):
            self.assertFalse(launcher._port_is_free())

    def test_occupied_port_with_missing_health_endpoint_is_not_restarted(self):
        failure = HTTPError(launcher.HEALTH_URL, 404, 'Not found', {}, None)
        with patch('launcher.urlopen', side_effect=failure), patch('launcher._spawn_console') as spawn:
            with self.assertRaises(launcher.LauncherError):
                launcher.ensure_console()
            spawn.assert_not_called()

    def test_start_failure_is_reported_without_opening_browser(self):
        with patch('launcher._probe_console', return_value=False), \
             patch('launcher._spawn_console', side_effect=OSError('cannot execute')), \
             patch('launcher.webbrowser.open') as browser:
            with self.assertRaisesRegex(launcher.LauncherError, '无法启动'):
                launcher.open_console()
            browser.assert_not_called()

    def test_early_exit_is_reported(self):
        process = Mock()
        process.poll.return_value = 1
        with patch('launcher._probe_console', return_value=False), patch('launcher._spawn_console', return_value=process):
            with self.assertRaisesRegex(launcher.LauncherError, '启动后退出'):
                launcher.ensure_console()
            process.kill.assert_not_called()
            process.terminate.assert_not_called()

    def test_startup_timeout_does_not_kill_any_process(self):
        process = Mock()
        with patch('launcher._probe_console', return_value=False), \
             patch('launcher._spawn_console', return_value=process), \
             patch('launcher.time.monotonic', side_effect=[0, 9]):
            with self.assertRaisesRegex(launcher.LauncherError, '8 秒'):
                launcher.ensure_console()
            process.kill.assert_not_called()
            process.terminate.assert_not_called()

    def test_open_console_starts_service_before_opening_browser(self):
        with patch('launcher.ensure_console', return_value=launcher.CONSOLE_URL) as ensure, \
             patch('launcher.webbrowser.open', return_value=True) as browser:
            self.assertEqual(launcher.open_console(), launcher.CONSOLE_URL)
            ensure.assert_called_once_with()
            browser.assert_called_once_with(launcher.CONSOLE_URL, new=2)


if __name__ == '__main__':
    unittest.main()
