import os

from typing import Optional, Any
from datetime import datetime

from fruition.api.server.webservice.base import WebServiceAPIServerBase, WebServiceAPIHandlerRegistry
from fruition.api.middleware.webservice.authentication.digest import DigestAuthenticationMiddleware

from webob import Request, Response

class LogAggregateServer(WebServiceAPIServerBase, DigestAuthenticationMiddleware):
    """
    A simple server that aggregates log files.
    """
    handlers = WebServiceAPIHandlerRegistry()

    def get_log_file(
        self,
        tag: Optional[str]=None,
        date: Optional[str]=None,
    ) -> str:
        """
        Gets the log file to append to.
        """
        if tag is None:
            tag = "default"
        log_dir = self.configuration.get("application.directory", "/var/log")
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(log_dir, f"fruition-{tag}-{date}.log")

    @handlers.methods("POST")
    @handlers.path(r"^(/(?P<tag>[^/]+)?)?$")
    def append(
        self,
        request: Request,
        response: Response,
        tag: Optional[str]=None
    ) -> None:
        """
        Appends plain text data to a log file.
        """
        log_file = self.get_log_file(tag)
        with open(log_file, "a") as f:
            f.write(request.body.decode("utf-8"))
        response.status = 204

    @handlers.methods("GET")
    @handlers.path(r"^(/(?P<tag>[^/]+)(/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}))?)?$")
    def read(
        self,
        request: Request,
        response: Response,
        tag: Optional[str]=None,
        date: Optional[str]=None
    ) -> None:
        """
        Reads a log file.
        """
        log_file = self.get_log_file(tag, date)
        if not os.path.exists(log_file):
            response.status = 404
            response.text = f"Log file {log_file} not found."
            return
        with open(log_file, "r") as f:
            response.text = f.read()
