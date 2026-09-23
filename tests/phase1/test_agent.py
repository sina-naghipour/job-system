import pytest

from packages.agent.main import DockerExecutor


class FakeContainer:
    def __init__(self, exit_code=0, stdout="ok", stderr=""):
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self.removed = False

    def wait(self) -> dict:
        return {"StatusCode": self._exit_code}

    def logs(self, stdout=True, stderr=False) -> bytes:
        if stdout and not stderr:
            return self._stdout.encode()
        if stderr and not stdout:
            return self._stderr.encode()
        return b""

    def remove(self, force=False) -> None:
        self.removed = True


class FakeDockerClient:
    def __init__(self, container: FakeContainer) -> None:
        self._container = container
        self.containers = self

    def run(self, **kwargs) -> FakeContainer:
        return self._container


def _executor(container: FakeContainer) -> DockerExecutor:
    executor = DockerExecutor.__new__(DockerExecutor)
    executor._client = FakeDockerClient(container)
    return executor


async def test_run_success() -> None:
    executor = _executor(FakeContainer(0, "hello", ""))
    code, out, err = await executor.run("alpine", ["echo"])
    assert (code, out, err) == (0, "hello", "")


async def test_run_failure() -> None:
    executor = _executor(FakeContainer(42, "", "boom"))
    code, out, err = await executor.run("alpine", ["false"])
    assert code == 42
    assert err == "boom"


async def test_run_removes_container() -> None:
    container = FakeContainer()
    executor = _executor(container)
    await executor.run("alpine", ["echo"])
    assert container.removed