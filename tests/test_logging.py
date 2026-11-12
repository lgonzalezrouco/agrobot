import logging
from logging.handlers import BufferingHandler

from agrobot.core.logging import configure_logging


def test_access_log_never_contains_the_query_string() -> None:
    configure_logging()
    access = logging.getLogger("uvicorn.access")
    captured = BufferingHandler(capacity=10)
    access.addHandler(captured)
    try:
        access.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            "/users?phone_number=%2B5491122334455",
            "1.1",
            200,
        )
    finally:
        access.removeHandler(captured)

    assert [record.getMessage() for record in captured.buffer] == [
        '127.0.0.1:5000 - "GET /users HTTP/1.1" 200'
    ]
