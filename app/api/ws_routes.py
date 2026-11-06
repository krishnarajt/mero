import asyncio
import logging

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.database import SessionLocal
from app.enums import CloseCode
from app.services import board_service, room_service
from app.services.auth_service import read_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["live"])


@router.websocket("/ws/boards/{board_id}")
async def board_socket(ws: WebSocket, board_id: str):
    await ws.accept()
    # Auth is the first frame rather than a query parameter, so the token
    # never shows up in proxy access logs.
    try:
        first = orjson.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        parsed = read_token(first.get("token", "")) if first.get("t") == "auth" else None
    except Exception:
        parsed = None
    if not parsed:
        await ws.close(CloseCode.UNAUTHORIZED)
        return
    user_id, username = parsed
    async with SessionLocal() as db:
        allowed = await board_service.board_access(db, board_id, user_id)
    if not allowed:
        await ws.close(CloseCode.NOT_FOUND)
        return

    conn = room_service.Conn(ws, user_id, username)
    conn.sender = asyncio.create_task(conn.run_sender())
    try:
        room = await room_service.join(board_id, conn)
    except Exception:
        logger.exception("Could not open board %s", board_id)
        conn.sender.cancel()
        await ws.close(CloseCode.SERVER_ERROR)
        return

    try:
        while not conn.closed:
            text = await ws.receive_text()
            if len(text) > room_service.MAX_MESSAGE_BYTES:
                continue
            try:
                msg = orjson.loads(text)
            except orjson.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                room.handle(conn, msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        conn.closed = True
        conn.sender.cancel()
        room_service.leave(room, conn)
