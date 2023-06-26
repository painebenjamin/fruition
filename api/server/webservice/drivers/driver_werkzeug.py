from __future__ import annotations

import ssl
from typing import Optional, TYPE_CHECKING
from werkzeug.serving import run_simple
from pibble.util.log import logger

if TYPE_CHECKING:
    from pibble.api.server.webservice.base import WebServiceAPIServerBase


def run_werkzeug(
    application: WebServiceAPIServerBase,
    host: str,
    port: int,
    secure: bool = False,
    cert: Optional[str] = None,
    key: Optional[str] = None,
    chain: Optional[str] = None,
    workers: Optional[int] = None,
) -> None:
    """
    Runs the werkzeug HTTP server synchronously.
    """
    ssl_context = None
    if secure and cert is not None and key is not None:
        logger.info(
            f"Loading SSL certificate chain from keyfile {key:s}, certfile {cert:s}"
        )
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    elif secure:
        logger.warning(
            "No SSL keyfile/certfile specific, but SSL enabled. If this server is being proxied through another service that provides SSL context this is okay, otherwise connections will fail."
        )
    run_simple(host, port, application.wsgi(), ssl_context=ssl_context)
