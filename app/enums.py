from enum import IntEnum


class CloseCode(IntEnum):
    """Websocket close codes. The frontend's sync.ts acts on these."""

    SERVER_ERROR = 1011
    # Fell too far behind on sends; the client reconnects and re-syncs.
    TOO_SLOW = 4008
    # Missing or bad token: the client goes to the login page.
    UNAUTHORIZED = 4401
    # No such board, not a member, or the board was deleted.
    NOT_FOUND = 4404
