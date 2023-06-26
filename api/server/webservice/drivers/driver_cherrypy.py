from __future__ import annotations

import cherrypy
from typing import Optional, TYPE_CHECKING
from multiprocessing import cpu_count
from pibble.util.log import logger

if TYPE_CHECKING:
    from pibble.api.server.webservice.base import WebServiceAPIServerBase


def run_cherrypy(
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
    Runs the cherrypy engine synchronously.
    """
    cherrypy.tree.graft(application.wsgi(), "/")
    cherrypy.server.unsubscribe()
    cherrypy.config.update(
        {"global": {"environment": "production"}}
    )  # Disable reloading

    server = cherrypy._cpserver.Server()
    server.socket_host = host
    server.socket_port = port
    server.thread_pool = workers if workers is not None else cpu_count() * 2 - 1
    server.max_request_body_size = 0  # No limit
    server.socket_timeout = 300  # 5 minutes for large uploads

    if secure and cert is not None and key is not None:
        server.ssl_model = "pyopenssl"
        server.ssl_certificate = cert
        server.ssl_private_key = key
        if chain is not None:
            server.ssl_certificate_chain = chain
        logger.info(
            f"Loading SSL certificate chain from keyfile {key:s}, certfile {cert:s}, chain {chain}"
        )
    elif secure:
        logger.warning(
            "No SSL keyfile/certfile specific, but SSL enabled. If this server is being proxied through another service that provides SSL context this is okay, otherwise connections will fail."
        )

    server.subscribe()
    cherrypy.engine.subscribe("exit", lambda: application.destroy())
    cherrypy.engine.start()
    cherrypy.engine.block()
