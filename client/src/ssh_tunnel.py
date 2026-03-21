"""SSH tunnel manager — forwards a local TCP port to a remote device's
localhost:8100 (WDA) via an SSH connection over WiFi.

WDA binds to 127.0.0.1 on the device, so it's not reachable directly over
WiFi. This module creates an SSH tunnel through the device's OpenSSH server
(which binds to 0.0.0.0) to reach WDA's loopback port.

Each device gets one SSHTunnel instance, managed by usb_monitor.
"""

import logging
import socket
import threading

logger = logging.getLogger(__name__)

SSH_DEFAULT_USER = "root"
SSH_DEFAULT_PASS = "alpine"
SSH_DEFAULT_PORT = 22
WDA_REMOTE_PORT = 8100


class SSHTunnel:
    """Forward localhost:<local_port> -> device(SSH) -> localhost:<remote_port>."""

    def __init__(
        self,
        device_ip: str,
        local_port: int,
        remote_port: int = WDA_REMOTE_PORT,
        username: str = SSH_DEFAULT_USER,
        password: str = SSH_DEFAULT_PASS,
        ssh_port: int = SSH_DEFAULT_PORT,
    ):
        self.device_ip = device_ip
        self.local_port = local_port
        self.remote_port = remote_port
        self.username = username
        self.password = password
        self.ssh_port = ssh_port
        self._ssh = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        """Open SSH connection and start local TCP listener (blocking call)."""
        import paramiko

        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            self.device_ip,
            port=self.ssh_port,
            username=self.username,
            password=self.password,
            timeout=10,
            banner_timeout=10,
        )

        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", self.local_port))
        self._server.listen(5)
        self._server.settimeout(1.0)

        self._running = True
        self._thread = threading.Thread(
            target=self._accept_loop,
            daemon=True,
            name=f"ssh-tunnel-{self.device_ip}:{self.local_port}",
        )
        self._thread.start()
        logger.info(
            "SSH tunnel: localhost:%d -> %s(SSH:%d) -> localhost:%d",
            self.local_port, self.device_ip, self.ssh_port, self.remote_port,
        )

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                transport = self._ssh.get_transport()
                if not transport or not transport.is_active():
                    client.close()
                    break
                channel = transport.open_channel(
                    "direct-tcpip",
                    ("localhost", self.remote_port),
                    addr,
                )
            except Exception:
                client.close()
                continue

            threading.Thread(
                target=self._pipe, args=(client, channel), daemon=True
            ).start()
            threading.Thread(
                target=self._pipe, args=(channel, client), daemon=True
            ).start()

    @staticmethod
    def _pipe(src, dst):
        try:
            while True:
                data = src.recv(32768)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.close()
                except Exception:
                    pass

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None

    def is_alive(self) -> bool:
        if not self._ssh or not self._running:
            return False
        transport = self._ssh.get_transport()
        return transport is not None and transport.is_active()
