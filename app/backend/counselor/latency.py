"""Bound one speculative retry for a voice request that has not produced text."""

import asyncio


async def voice_reply(backend, messages, *, on_delta=None, retry_delay=3.5):
    winner = None
    ready = asyncio.Event()
    tasks = []

    async def attempt(index):
        nonlocal winner

        def delta(text):
            nonlocal winner
            if not text:
                return
            if winner is None:
                winner = index
                ready.set()
            if winner == index and on_delta:
                on_delta(text)

        result = await backend.reply(messages, on_delta=delta)
        if winner is None:
            winner = index
            ready.set()
        return result

    signal = asyncio.create_task(ready.wait())
    tasks.append(asyncio.create_task(attempt(0)))
    try:
        done, _ = await asyncio.wait(
            (tasks[0], signal), timeout=retry_delay, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            # Same provider, model and prompt; never route private text elsewhere.
            tasks.append(asyncio.create_task(attempt(1)))
        pending = set(tasks)
        while winner is None:
            done, _ = await asyncio.wait((*pending, signal), return_when=asyncio.FIRST_COMPLETED)
            failed = [task for task in done if task is not signal and task.exception() is not None]
            pending.difference_update(failed)
            if not pending:
                raise failed[-1].exception()
        for index, task in enumerate(tasks):
            if index != winner:
                task.cancel()
        return await tasks[winner]
    finally:
        # Fence late deltas even if a provider delays acknowledging cancellation.
        winner = -1
        signal.cancel()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(signal, *tasks, return_exceptions=True)
