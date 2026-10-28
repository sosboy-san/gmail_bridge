"""No external services: reproduce silent IMAP peers over loopback sockets."""

import contextlib
import imaplib
import io
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock, call, patch

from app import main
from app.imap_client import ImapClient


class SilentPeer:
    def __init__(self, *, greet=False):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.greet = greet
        self.done = threading.Event()
        self.closed_by_client = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        self.listener.settimeout(2)
        try:
            connection, _ = self.listener.accept()
            with connection:
                connection.settimeout(0.1)
                if self.greet:
                    connection.sendall(b'* OK synthetic test peer\r\n')
                while not self.done.is_set():
                    try:
                        command = connection.recv(4096)
                    except socket.timeout:
                        continue
                    if not command:
                        self.closed_by_client.set()
                        return
                    if b'CAPABILITY' in command:
                        tag = command.split()[0]
                        connection.sendall(
                            b'* CAPABILITY IMAP4rev1 STARTTLS\r\n' + tag + b' OK done\r\n'
                        )
                    # Deliberately never respond to STARTTLS or other commands.
        except OSError:
            pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.done.set()
        self.listener.close()
        self.thread.join(timeout=3)


class ImapTimeoutTests(unittest.TestCase):
    def test_silent_greeting_times_out_and_closes_connection(self):
        self.check_silent_peer(greet=False)

    def test_silent_starttls_times_out_and_closes_connection(self):
        self.check_silent_peer(greet=True)

    def test_command_read_timeout_and_close_after_failed_read(self):
        with SilentPeer(greet=True) as peer:
            client = ImapClient('127.0.0.1', peer.port, 'test', 'synthetic', timeout=0.2)
            client.imap = imaplib.IMAP4('127.0.0.1', peer.port, timeout=client.timeout)
            client.imap.state = 'AUTH'
            with self.assertRaises(TimeoutError):
                client.select_mailbox()
            client.close()
            self.assertIsNone(client.imap)
            self.assertTrue(peer.closed_by_client.wait(2))

    def check_silent_peer(self, *, greet):
        with SilentPeer(greet=greet) as peer:
            client = ImapClient('127.0.0.1', peer.port, 'test', 'synthetic', timeout=0.2)
            started = time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(TimeoutError):
                client.connect()
            self.assertLess(time.monotonic() - started, 3)
            self.assertIsNone(client.imap)
            self.assertTrue(peer.closed_by_client.wait(2))

    def test_login_timeout_discards_without_logout_and_next_attempt_recovers(self):
        failed, healthy = MagicMock(), MagicMock()
        failed.login.side_effect = TimeoutError('synthetic')
        client = ImapClient('imap.example.invalid', 143, 'test', 'synthetic')
        with patch('app.imap_client.imaplib.IMAP4', side_effect=[failed, healthy]) as factory:
            with patch.object(main.time, 'sleep') as sleep:
                main.connect_imap_with_retry(client)
        self.assertEqual(factory.call_args_list, [
            call('imap.example.invalid', 143, timeout=30),
            call('imap.example.invalid', 143, timeout=30),
        ])
        failed.shutdown.assert_called_once()
        failed.logout.assert_not_called()
        sleep.assert_called_once_with(10)
        self.assertIs(client.imap, healthy)
        healthy.login.assert_called_once_with('test', 'synthetic')

    def test_all_timeouts_leave_no_connection_and_exit_retry_loop(self):
        clients = [MagicMock() for _ in range(3)]
        for connection in clients:
            connection.starttls.side_effect = TimeoutError('synthetic')
        client = ImapClient('imap.example.invalid', 143, 'test', 'synthetic')
        with patch('app.imap_client.imaplib.IMAP4', side_effect=clients):
            with patch.object(main.time, 'sleep') as sleep, self.assertRaises(TimeoutError):
                main.connect_imap_with_retry(client)
        self.assertEqual(sleep.call_args_list, [call(10), call(30)])
        self.assertIsNone(client.imap)
        for connection in clients:
            connection.shutdown.assert_called_once()
            connection.logout.assert_not_called()

    def test_logout_failure_still_closes_socket_and_clears_mailbox(self):
        client = ImapClient('imap.example.invalid', 143, 'test', 'synthetic')
        connection = MagicMock()
        client.imap = connection
        client.current_mailbox = 'INBOX'
        client.readonly = False
        connection.logout.side_effect = TimeoutError('synthetic')
        client.close()
        connection.shutdown.assert_called_once()
        self.assertIsNone(client.imap)
        self.assertIsNone(client.current_mailbox)
        self.assertTrue(client.readonly)

    def test_shutdown_failure_still_releases_local_resources(self):
        client = ImapClient('imap.example.invalid', 143, 'test', 'synthetic')
        connection = MagicMock()
        client.imap = connection
        connection.shutdown.side_effect = OSError('synthetic')
        connection.file.close.side_effect = OSError('synthetic')
        client._discard()
        connection.sock.close.assert_called_once()
        self.assertIsNone(client.imap)


if __name__ == '__main__':
    unittest.main()
