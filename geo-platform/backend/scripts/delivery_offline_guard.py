"""Pytest offline boundary: a fixture must never silently consume paid services."""
import ipaddress
import socket

import pytest


@pytest.fixture(autouse=True)
def deny_external_connections(monkeypatch):
    original = socket.socket.connect

    def guarded(sock, address):
        if sock.family == socket.AF_UNIX:
            return original(sock, address)
        host = address[0]
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == 'localhost'
        if not local:
            raise RuntimeError('OFFLINE_ACCEPTANCE_EXTERNAL_CONNECTION_BLOCKED')
        return original(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', guarded)
