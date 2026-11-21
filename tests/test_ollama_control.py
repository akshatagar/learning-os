"""Starting and stopping the local Ollama server from the home page."""
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from web import ollama_control
from web.app import create_app


def test_running_when_the_server_answers():
    assert ollama_control.is_running(get=lambda url, timeout: httpx.Response(200)) is True


def test_not_running_when_nothing_answers():
    def refused(url, timeout):
        raise httpx.ConnectError("refused")

    assert ollama_control.is_running(get=refused) is False


def test_start_runs_ollama_serve_with_no_window():
    calls = []
    ollama_control.start(popen=lambda args, **kw: calls.append((args, kw)),
                         find=lambda: r"C:\Ollama\ollama.exe")
    [(args, kw)] = calls
    assert args == [r"C:\Ollama\ollama.exe", "serve"]
    assert kw["creationflags"] == ollama_control.NO_WINDOW | ollama_control.DETACHED
    assert kw["stdout"] is subprocess.DEVNULL and kw["stderr"] is subprocess.DEVNULL


@pytest.mark.skipif(sys.platform != "win32", reason="the flags exist only on Windows")
def test_on_windows_the_server_gets_no_console_window():
    assert ollama_control.NO_WINDOW == subprocess.CREATE_NO_WINDOW
    assert ollama_control.DETACHED == subprocess.DETACHED_PROCESS


def test_start_without_ollama_installed_is_an_error():
    with pytest.raises(FileNotFoundError):
        ollama_control.start(popen=lambda *a, **k: None, find=lambda: None)


def test_stop_ends_the_server_and_the_tray_app():
    calls = []
    ollama_control.stop(run=lambda args, **kw: calls.append(args))
    killed = {args[args.index("/IM") + 1] for args in calls}
    assert killed == {"ollama.exe", "ollama app.exe"}
    assert all(args[0] == "taskkill" and "/F" in args for args in calls)


class FakeOllama:
    def __init__(self, running=False, installed=True):
        self.running, self.installed, self.started, self.stopped = running, installed, 0, 0

    def is_running(self):
        return self.running

    def start(self):
        if not self.installed:
            raise FileNotFoundError("ollama")
        self.started += 1

    def stop(self):
        self.stopped += 1


def _client(engine, collection, fake):
    app = create_app(engine, collection)
    app.state.ollama = fake
    return TestClient(app)


def test_the_home_page_can_ask_whether_ollama_runs(engine, collection):
    assert _client(engine, collection, FakeOllama(running=True)).get("/ollama").json() == \
        {"running": True}


def test_start_starts_ollama_only_when_it_is_not_running(engine, collection):
    fake = FakeOllama(running=False)
    client = _client(engine, collection, fake)
    assert client.post("/ollama/start").json() == {"started": True}
    fake.running = True
    assert client.post("/ollama/start").json() == {"started": False}
    assert fake.started == 1


def test_start_reports_when_ollama_is_not_installed(engine, collection):
    client = _client(engine, collection, FakeOllama(installed=False))
    assert client.post("/ollama/start").status_code == 404


def test_stop_stops_ollama(engine, collection):
    fake = FakeOllama(running=True)
    assert _client(engine, collection, fake).post("/ollama/stop").json() == {"ok": True}
    assert fake.stopped == 1
