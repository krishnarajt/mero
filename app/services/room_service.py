"""Live boards: one in-memory room per open board, relayed over websockets.

The hot path never touches the database. A message comes in, the room's
in-memory state is updated, and the message is queued to every other
connection. Finished strokes and deletions go onto the write-behind queue in
persist_service.py, which a background task flushes in batches.

Because the state lives in this process, the server must run as exactly one
process (one uvicorn worker, one replica).

Wire protocol, JSON text frames. Server frames may also be a JSON array of
these objects when several were queued at once.

  client -> server
    {"t":"auth","token":str}                          first frame, required
    {"t":"b","id":str,"c":"#rrggbb","w":num,"p":[x,y,..]}   stroke begin
    {"t":"a","id":str,"p":[x,y,..]}                    stroke points
    {"t":"e","id":str}                                 stroke end
    {"t":"d","ids":[str]}                              delete strokes
    {"t":"r","s":[stroke]}                             add whole strokes (shapes,
                                                       duplicates, undone deletes)
    {"t":"u","s":[stroke]}                             replace existing strokes
                                                       (move, scale, restyle, group)
    {"t":"m","x":num,"y":num} | {"t":"m"}              cursor / cursor gone
    {"t":"ping","ts":num}

  server -> client
    {"t":"init","cid":int,"strokes":[stroke],"live":[stroke],"peers":[{"cid","name"}]}
    the stroke frames above, relayed as-is ("m" gains "cid")
    {"t":"join","cid":int,"name":str} / {"t":"leave","cid":int}
    {"t":"pong","ts":num}

A stroke is {"id","c","w","p","k"?,"o"?,"g"?}: colour, width in world units,
a flat list of world coordinates, "k":"l" for straight segments (shapes),
"o" for opacity below 1 (highlighter), and "g" a group id shared by strokes
that are selected and moved together.
"""

import asyncio
import itertools
import logging
import re

import orjson
from fastapi import WebSocket
from sqlalchemy import select

from app.db.database import engine
from app.db.models import Stroke
from app.enums import CloseCode
from app.services.persist_service import persister

logger = logging.getLogger(__name__)

# Guards against a single client filling memory. A handwritten word is a few
# hundred points, so these are far above anything real.
MAX_POINTS_PER_STROKE = 40_000
MAX_MESSAGE_BYTES = 1_000_000
# Frames queued for one client before it counts as hopelessly behind.
MAX_QUEUE = 4000

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_cid_counter = itertools.count(1)


def _dumps(obj) -> str:
    return orjson.dumps(obj).decode()


def _valid_points(p) -> bool:
    return (
        isinstance(p, list)
        and len(p) % 2 == 0
        and len(p) <= MAX_POINTS_PER_STROKE * 2
        and all(type(v) is float or type(v) is int for v in p)
    )


def _valid_id(i) -> bool:
    return isinstance(i, str) and 0 < len(i) <= 32


def _clean_stroke(s) -> dict | None:
    if not isinstance(s, dict):
        return None
    sid, c, w, p = s.get("id"), s.get("c"), s.get("w"), s.get("p")
    if not _valid_id(sid) or not isinstance(c, str) or not _COLOR.match(c):
        return None
    if not isinstance(w, (int, float)) or not (0 < w < 1e6) or not _valid_points(p):
        return None
    out = {"id": sid, "c": c, "w": w, "p": p}
    k, o, g = s.get("k"), s.get("o"), s.get("g")
    if k is not None:
        if k != "l":
            return None
        out["k"] = k
    if o is not None:
        if not isinstance(o, (int, float)) or not (0 < o <= 1):
            return None
        if o < 1:
            out["o"] = o
    if g is not None:
        if not _valid_id(g):
            return None
        out["g"] = g
    return out


# --------------------------------------------------------------------------
# Connections and rooms
# --------------------------------------------------------------------------


class Conn:
    def __init__(self, ws: WebSocket, user_id: int, username: str):
        self.ws = ws
        self.cid = next(_cid_counter)
        self.user_id = user_id
        self.username = username
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.sender: asyncio.Task | None = None
        self.closed = False

    def send(self, msg: str):
        if self.closed:
            return
        if self.queue.qsize() > MAX_QUEUE:
            # Too far behind to ever catch up; it will reconnect and re-sync.
            self.closed = True
            asyncio.create_task(self._close(CloseCode.TOO_SLOW))
            return
        self.queue.put_nowait(msg)

    async def _close(self, code: int):
        try:
            await self.ws.close(code)
        except Exception:
            pass

    async def run_sender(self):
        try:
            while True:
                msg = await self.queue.get()
                if self.queue.empty():
                    await self.ws.send_text(msg)
                    continue
                # Several frames queued up: ship them as one array frame.
                batch = [msg]
                while not self.queue.empty() and len(batch) < 256:
                    batch.append(self.queue.get_nowait())
                await self.ws.send_text("[" + ",".join(batch) + "]")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.closed = True


class Room:
    def __init__(self, board_id: str):
        self.board_id = board_id
        # Paint order is insertion order. Values are the stroke's JSON text.
        self.committed: dict[str, str] = {}
        # In-progress strokes: id -> (stroke dict, owning conn)
        self.live: dict[str, tuple[dict, Conn]] = {}
        self.conns: set[Conn] = set()
        self.loaded = asyncio.Event()
        self.failed = False

    async def load(self):
        await persister.drain()
        async with engine.connect() as conn:
            rows = await conn.execute(
                select(Stroke.id, Stroke.data).where(Stroke.board_id == self.board_id).order_by(Stroke.seq)
            )
            for sid, data in rows:
                self.committed[sid] = data
        self.loaded.set()

    def broadcast(self, msg: str, exclude: Conn | None = None):
        for c in self.conns:
            if c is not exclude:
                c.send(msg)

    def init_message(self, me: Conn) -> str:
        live = [_dumps(s) for s, _ in self.live.values()]
        peers = [{"cid": c.cid, "name": c.username} for c in self.conns if c is not me]
        return (
            '{"t":"init","cid":' + str(me.cid)
            + ',"peers":' + _dumps(peers)
            + ',"strokes":[' + ",".join(self.committed.values()) + "]"
            + ',"live":[' + ",".join(live) + "]}"
        )

    def commit(self, sid: str, user_id: int | None):
        entry = self.live.pop(sid, None)
        if not entry:
            return
        stroke = entry[0]
        if not stroke["p"]:
            return
        data = _dumps(stroke)
        self.committed[sid] = data
        persister.insert(self.board_id, sid, user_id, data)

    def handle(self, conn: Conn, msg: dict):
        t = msg.get("t")
        if t == "a":
            sid = msg.get("id")
            entry = self.live.get(sid)
            p = msg.get("p")
            if not entry or entry[1] is not conn or not _valid_points(p):
                return
            stroke = entry[0]
            if len(stroke["p"]) + len(p) > MAX_POINTS_PER_STROKE * 2:
                return
            stroke["p"].extend(p)
            self.broadcast(_dumps({"t": "a", "id": sid, "p": p}), conn)
        elif t == "m":
            x, y = msg.get("x"), msg.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                self.broadcast(_dumps({"t": "m", "cid": conn.cid, "x": x, "y": y}), conn)
            else:
                self.broadcast(_dumps({"t": "m", "cid": conn.cid}), conn)
        elif t == "b":
            stroke = _clean_stroke(msg)
            if not stroke or stroke["id"] in self.live or stroke["id"] in self.committed:
                return
            self.live[stroke["id"]] = (stroke, conn)
            self.broadcast(_dumps({"t": "b", **stroke}), conn)
        elif t == "e":
            sid = msg.get("id")
            entry = self.live.get(sid)
            if not entry or entry[1] is not conn:
                return
            self.commit(sid, conn.user_id)
            self.broadcast(_dumps({"t": "e", "id": sid}), conn)
        elif t == "d":
            ids = msg.get("ids")
            if not isinstance(ids, list):
                return
            gone = [i for i in ids if isinstance(i, str) and self.committed.pop(i, None) is not None]
            if gone:
                persister.delete(self.board_id, gone)
                self.broadcast(_dumps({"t": "d", "ids": gone}), conn)
        elif t == "r":
            items = msg.get("s")
            if not isinstance(items, list):
                return
            restored = []
            for raw in items:
                s = _clean_stroke(raw)
                if not s or s["id"] in self.committed or s["id"] in self.live:
                    continue
                data = _dumps(s)
                self.committed[s["id"]] = data
                persister.insert(self.board_id, s["id"], conn.user_id, data)
                restored.append(s)
            if restored:
                self.broadcast(_dumps({"t": "r", "s": restored}), conn)
        elif t == "u":
            items = msg.get("s")
            if not isinstance(items, list):
                return
            changed = []
            for raw in items:
                s = _clean_stroke(raw)
                if not s or s["id"] not in self.committed:
                    continue
                data = _dumps(s)
                # Assigning an existing key keeps its place, so z-order holds.
                self.committed[s["id"]] = data
                persister.update(self.board_id, s["id"], data)
                changed.append(s)
            if changed:
                self.broadcast(_dumps({"t": "u", "s": changed}), conn)
        elif t == "ping":
            conn.send(_dumps({"t": "pong", "ts": msg.get("ts")}))

    def drop_conn(self, conn: Conn):
        self.conns.discard(conn)
        # Whatever this client was drawing when it vanished is kept.
        for sid in [sid for sid, (_, owner) in self.live.items() if owner is conn]:
            self.commit(sid, conn.user_id)
            self.broadcast(_dumps({"t": "e", "id": sid}))
        self.broadcast(_dumps({"t": "leave", "cid": conn.cid}))


_rooms: dict[str, Room] = {}


async def join(board_id: str, conn: Conn) -> Room:
    room = _rooms.get(board_id)
    if room is None:
        room = Room(board_id)
        _rooms[board_id] = room
        try:
            await room.load()
        except Exception:
            _rooms.pop(board_id, None)
            room.failed = True
            room.loaded.set()
            raise
    else:
        await room.loaded.wait()
        if room.failed:
            raise RuntimeError("board failed to load")
    room.conns.add(conn)
    conn.send(room.init_message(conn))
    room.broadcast(_dumps({"t": "join", "cid": conn.cid, "name": conn.username}), conn)
    return room


def leave(room: Room, conn: Conn):
    room.drop_conn(conn)
    if not room.conns and _rooms.get(room.board_id) is room:
        # Committed strokes are already queued for the database; load()
        # drains that queue before reading, so dropping the room is safe.
        del _rooms[room.board_id]


async def close_board(board_id: str):
    room = _rooms.pop(board_id, None)
    if not room:
        return
    for c in list(room.conns):
        c.closed = True
        await c._close(CloseCode.NOT_FOUND)
    room.conns.clear()
    room.live.clear()
