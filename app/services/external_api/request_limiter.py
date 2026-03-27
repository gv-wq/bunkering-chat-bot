import asyncio


class RequestLimiter:
    def __init__(self, max_concurrent: int, rps: float):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._interval = 1 / rps
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = asyncio.get_running_loop().time()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = asyncio.get_running_loop().time()

        await self._sem.acquire()

    def release(self):
        self._sem.release()
