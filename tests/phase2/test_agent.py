from packages.agent.main import DockerExecutor


class FakeContainer:
    def __init__(self, exit_code: int = 0, stdout: str = "ok", stderr: str = "") -> None:
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self.removed = False
        self.killed = False

    def wait(self) -> dict:
        return {"StatusCode": self._exit_code}

    def logs(self, stdout: bool = True, stderr: bool = False) -> bytes:
        if stdout and not stderr:
            return self._stdout.encode()
        if stderr and not stdout:
            return self._stderr.encode()
        return b""

    def remove(self, force: bool = False) -> None:
        self.removed = True

    def kill(self) -> None:
        self.killed = True


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


async def test_start_returns_container() -> None:
    container = FakeContainer()
    executor = _executor(container)
    result = await executor.start("alpine", ["echo"])
    assert result is container


async def test_wait_returns_exit_code_and_output() -> None:
    container = FakeContainer(exit_code=0, stdout="hello", stderr="")
    executor = _executor(container)
    code, out, err = await executor.wait(container)
    assert (code, out, err) == (0, "hello", "")


async def test_wait_returns_failure() -> None:
    container = FakeContainer(exit_code=42, stdout="", stderr="boom")
    executor = _executor(container)
    code, out, err = await executor.wait(container)
    assert code == 42
    assert err == "boom"


async def test_wait_removes_container() -> None:
    container = FakeContainer()
    executor = _executor(container)
    await executor.wait(container)
    assert container.removed


async def test_kill_marks_container_killed() -> None:
    container = FakeContainer()
    executor = _executor(container)
    await executor.kill(container)
    assert container.killed