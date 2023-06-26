from __future__ import annotations

from typing import Optional, TYPE_CHECKING
from multiprocessing import cpu_count
from gunicorn.app.base import Application
from pibble.util.log import logger

if TYPE_CHECKING:
    from pibble.api.server.webservice.base import WebServiceAPIServerBase
    from typeshed._wsgi import WSGIApplication


class PibbleGunicornApplication(Application):  # type: ignore
    """
    A simple extension of the gunicorn application base to work with the webservice.
    """

    def __init__(self, application: WSGIApplication, options: dict):
        self.options = options
        self.application = application
        super(PibbleGunicornApplication, self).__init__()

    def load_config(self) -> None:
        config = dict(
            [
                (key, self.options[key])
                for key in self.options
                if key in self.cfg.settings and self.options[key] is not None
            ]
        )
        for key in config:
            logger.debug(
                "Setting Gunicorn configuration key {0} = {1}".format(
                    key.lower(), config[key]
                )
            )
            self.cfg.set(key.lower(), config[key])

    def load(self) -> WSGIApplication:
        return self.application


def run_gunicorn(
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
    Runs the gunicorn application synchronously.
    """
    options = {
        "bind": f"{host:s}:{port:d}",
        "workers": cpu_count() * 2 + 1 if workers is None else workers,
        "worker_class": "gthread",
    }

    if secure and cert is not None and key is not None:
        options["keyfile"] = key
        options["certfile"] = cert
        logger.info(
            f"Loading SSL certificate chain from keyfile {key:s}, certfile {cert:s}"
        )
    elif secure:
        logger.warning(
            "No SSL keyfile/certfile specific, but SSL enabled. If this server is being proxied through another service that provides SSL context this is okay, otherwise connections will fail."
        )

    application = PibbleGunicornApplication(application.wsgi(), options)
    application.run()
