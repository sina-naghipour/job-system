from packages.server.log_broker import LogBroker


def test_publish_assigns_sequence_per_stream() -> None:
    broker = LogBroker()

    a = broker.publish("job_1", "stdout", "hello")
    b = broker.publish("job_1", "stdout", "world")
    c = broker.publish("job_1", "stderr", "boom")

    assert a.sequence == 1
    assert b.sequence == 2
    assert c.sequence == 1


def test_history_is_kept_per_job() -> None:
    broker = LogBroker()
    broker.publish("job_1", "stdout", "a")
    broker.publish("job_1", "stdout", "b")
    broker.publish("job_2", "stdout", "x")

    assert [c.chunk for c in broker.history("job_1")] == ["a", "b"]
    assert [c.chunk for c in broker.history("job_2")] == ["x"]


def test_history_empty_for_unknown_job() -> None:
    broker = LogBroker()
    assert broker.history("missing") == []


def test_history_cap_drops_oldest() -> None:
    broker = LogBroker(history_cap=3)
    for i in range(5):
        broker.publish("job_1", "stdout", str(i))

    chunks = [c.chunk for c in broker.history("job_1")]
    assert chunks == ["2", "3", "4"]


async def test_subscriber_receives_live_chunks() -> None:
    broker = LogBroker()
    queue, history = broker.subscribe("job_1")
    assert history == []

    broker.publish("job_1", "stdout", "a")
    broker.publish("job_1", "stdout", "b")

    assert queue.qsize() == 2
    assert (await queue.get()).chunk == "a"
    assert (await queue.get()).chunk == "b"


async def test_subscriber_receives_history_on_connect() -> None:
    broker = LogBroker()
    broker.publish("job_1", "stdout", "old")
    queue, history = broker.subscribe("job_1")

    assert [c.chunk for c in history] == ["old"]
    assert queue.qsize() == 0

    broker.publish("job_1", "stdout", "new")
    assert (await queue.get()).chunk == "new"


async def test_unsubscribe_stops_delivery() -> None:
    broker = LogBroker()
    queue, _ = broker.subscribe("job_1")
    broker.unsubscribe("job_1", queue)

    broker.publish("job_1", "stdout", "a")
    assert queue.qsize() == 0


async def test_multiple_subscribers_each_get_chunk() -> None:
    broker = LogBroker()
    q1, _ = broker.subscribe("job_1")
    q2, _ = broker.subscribe("job_1")

    broker.publish("job_1", "stdout", "a")

    assert (await q1.get()).chunk == "a"
    assert (await q2.get()).chunk == "a"


async def test_subscriber_queue_overflow_drops_oldest() -> None:
    broker = LogBroker(queue_cap=2)
    queue, _ = broker.subscribe("job_1")

    broker.publish("job_1", "stdout", "a")
    broker.publish("job_1", "stdout", "b")
    broker.publish("job_1", "stdout", "c")

    # Queue is capped at 2, oldest ("a") dropped.
    assert queue.qsize() == 2
    assert (await queue.get()).chunk == "b"
    assert (await queue.get()).chunk == "c"


async def test_subscribers_are_isolated_per_job() -> None:
    broker = LogBroker()
    q1, _ = broker.subscribe("job_1")
    q2, _ = broker.subscribe("job_2")

    broker.publish("job_1", "stdout", "a")

    assert q1.qsize() == 1
    assert q2.qsize() == 0


async def test_unsubscribe_unknown_is_noop() -> None:
    broker = LogBroker()
    import asyncio
    broker.unsubscribe("missing", asyncio.Queue())