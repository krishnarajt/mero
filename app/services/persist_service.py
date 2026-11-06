"""Write-behind persistence for strokes.

Rooms answer from memory and queue their writes here, so nothing on the
drawing path waits for the database. A single task drains the queue in
batches.
"""

import asyncio
import logging

from sqlalchemy import bindparam, delete, insert, update

from app.db.database import engine
from app.db.models import Stroke

logger = logging.getLogger(__name__)

# Plain Core statements on the table: executemany, no ORM bookkeeping.
_strokes = Stroke.__table__


class Persister:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        await self.queue.join()
        if self.task:
            self.task.cancel()

    def insert(self, board_id: str, stroke_id: str, user_id: int | None, data: str):
        self.queue.put_nowait(("ins", board_id, stroke_id, user_id, data))

    def delete(self, board_id: str, ids: list[str]):
        self.queue.put_nowait(("del", board_id, ids))

    def update(self, board_id: str, stroke_id: str, data: str):
        self.queue.put_nowait(("upd", board_id, stroke_id, data))

    async def drain(self):
        await self.queue.join()

    async def _run(self):
        while True:
            first = await self.queue.get()
            # A short pause lets a burst (an eraser sweep, several people
            # finishing strokes) land in one transaction.
            await asyncio.sleep(0.05)
            ops = [first]
            while not self.queue.empty() and len(ops) < 500:
                ops.append(self.queue.get_nowait())
            try:
                await self._apply(ops)
            except Exception:
                logger.exception("Batch write failed, retrying one by one")
                for op in ops:
                    try:
                        await self._apply([op])
                    except Exception:
                        logger.exception("Dropping write %s for board %s", op[0], op[1])
            finally:
                for _ in ops:
                    self.queue.task_done()

    async def _apply(self, ops):
        async with engine.begin() as conn:
            # Consecutive ops of the same kind run as one executemany; a change
            # of kind flushes, so the queue's order is kept.
            kind, pending = None, []

            async def flush():
                if not pending:
                    return
                if kind == "ins":
                    await conn.execute(insert(_strokes), pending)
                elif kind == "upd":
                    await conn.execute(_UPDATE, pending)
                pending.clear()

            for op in ops:
                if op[0] != kind:
                    await flush()
                    kind = op[0]
                if op[0] == "ins":
                    pending.append({"board_id": op[1], "id": op[2], "user_id": op[3], "data": op[4]})
                elif op[0] == "upd":
                    pending.append({"b_board": op[1], "b_id": op[2], "b_data": op[3]})
                else:
                    await conn.execute(delete(_strokes).where(_strokes.c.board_id == op[1], _strokes.c.id.in_(op[2])))
            await flush()


_UPDATE = (
    update(_strokes)
    .where(_strokes.c.board_id == bindparam("b_board"), _strokes.c.id == bindparam("b_id"))
    .values(data=bindparam("b_data"))
)

persister = Persister()
