from __future__ import annotations

import cherrypy
from typing import Optional, TYPE_CHECKING
from multiprocessing import cpu_count
from pibble.util.log import logger

if TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication


def run_cherrypy(
    application: WSGIApplication,
    host: str,
    port: int,
    secure: bool = False,
    cert: Optional[str] = None,
    key: Optional[str] = None,
    workers: Optional[int] = None,
) -> None:
    """
    Runs the cherrypy engine synchronously.
    """
    cherrypy.tree.graft(application, "/")
    cherrypy.server.unsubscribe()
    cherrypy.config.update(
        {"global": {"environment": "production"}}
    )  # Disable reloading

    server = cherrypy._cpserver.Server()
    server.socket_host = host
    server.socket_port = port
    server.thread_pool = workers if workers is not None else cpu_count() * 2 - 1

    if secure and cert is not None and key is not None:
        server.ssl_model = "pyopenssl"
        server.ssl_certificate = cert
        server.ssl_private_key = key
        logger.info(
            f"Loading SSL certificate chain from keyfile {key:s}, certfile {cert:s}"
        )
    elif secure:
        logger.warning(
            "No SSL keyfile/certfile specific, but SSL enabled. If this server is being proxied through another service that provides SSL context this is okay, otherwise connections will fail."
        )

    server.subscribe()
    cherrypy.engine.start()
    cherrypy.engine.block()
