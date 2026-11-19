from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import consumer


class NpmConsumerTests(unittest.TestCase):
    def attempt(self, code=0, text='installed'):
        return subprocess.CompletedProcess([], code, stdout=text)

    def clock(self):
        now = [0]
        def sleep(seconds):
            now[0] += seconds
        return now, sleep

    def test_delayed_registry_visibility_then_real_installation(self):
        now, sleep = self.clock()
        attempts = [self.attempt(1, 'npm error code ETARGET'), self.attempt(1, 'npm ERR! code E404'), self.attempt()]
        with patch.object(consumer.subprocess, 'run', side_effect=attempts) as run, \
                patch.object(consumer.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(consumer.time, 'sleep', side_effect=sleep):
            consumer.install_npm('@kompressr/sdk', '1.1.0', Path('.'), {}, timeout=10, retry_delay=1)
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertIn('--ignore-scripts', args)
            self.assertIn('--prefer-online', args)
            self.assertIn('@kompressr/sdk@1.1.0', args)
            self.assertNotIn('publish', args)

    def test_permanent_failure_is_not_retried(self):
        for error in ('EINTEGRITY', 'E401', 'EACCES', 'ERESOLVE'):
            with self.subTest(error=error), patch.object(consumer.subprocess, 'run', return_value=self.attempt(1, 'npm error code ' + error)) as run, patch.object(consumer.time, 'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'installation failed'):
                    consumer.install_npm('@kompressr/sdk', '1.1.0', Path('.'), {})
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_missing_version_eventually_fails(self):
        now, sleep = self.clock()
        with patch.object(consumer.subprocess, 'run', return_value=self.attempt(1, 'npm error code ETARGET')) as run, \
                patch.object(consumer.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(consumer.time, 'sleep', side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                consumer.install_npm('@kompressr/sdk', '1.1.0', Path('.'), {}, timeout=2, retry_delay=1)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(now[0], 2)

    def test_network_timeout_is_bounded_and_cancellation_propagates(self):
        now, sleep = self.clock()
        with patch.object(consumer.subprocess, 'run', side_effect=subprocess.TimeoutExpired('npm', 1)) as run, \
                patch.object(consumer.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(consumer.time, 'sleep', side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                consumer.install_npm('@kompressr/sdk', '1.1.0', Path('.'), {}, timeout=2, retry_delay=1)
            self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list], [2, 1])
        with patch.object(consumer.subprocess, 'run', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                consumer.install_npm('@kompressr/sdk', '1.1.0', Path('.'), {})


if __name__ == '__main__':
    unittest.main()
