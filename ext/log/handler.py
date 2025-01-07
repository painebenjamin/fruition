import logging

from typing import Any, Optional
from urllib.parse import urlparse

from fruition.ext.log.client import LogAggregateClient

class LogAggregateHandler(logging.Handler):
    """
    A handler class which sends log records to a log aggregate server.
    """
    def __init__(
        self,
        url: str,
        *args: Any,
        tag: Optional[str] = None,
        interval: int = 2,
        authentication: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """
        :param url: The URL of the log aggregate server.
        :param tag: The tag to use when sending logs to the server.
        :param interval: The interval in seconds to send logs to the server.
        :param authentication: The authentication method to use.
        :param username: The username to use for authentication.
        :param password: The password to use for authentication.
        """
        super(LogAggregateHandler, self).__init__(*args, **kwargs)
        parsed_url = urlparse(url)
        netloc_parts = parsed_url.netloc.split(":")
        secure = parsed_url.scheme == "https"
        if len(netloc_parts) == 2:
            host, port = netloc_parts
        else:
            host = netloc_parts[0]
            port = 443 if secure else 80

        self.tag = tag
        self.client = LogAggregateClient()
        config = {
            "client": {
                "host": host,
                "port": port,
                "path": parsed_url.path,
                "secure": secure,
            },
            "interval": interval,
            "authentication": {}
        }
        if authentication:
            config["authentication"][authentication] = {
                "username": username,
                "password": password
            }

        self.client.configure(**config)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a record.
        """
        self.client.log(self.format(record), tag=self.tag)
