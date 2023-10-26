"""
Utilities for logging - the global logger, and contexts for debugging.
"""
import os
import sys
import http.client
import socket

from logging import (
    Handler,
    StreamHandler,
    Formatter,
    LogRecord,
    Logger,
    getLogger,
    DEBUG,
)
from typing import Any, List
from logging.handlers import SysLogHandler, RotatingFileHandler
from termcolor import colored

from pibble.api.configuration import APIConfiguration

__all__ = [
    "logger",
    "ColoredLoggingFormatter",
    "UnifiedLoggingContext",
    "LevelUnifiedLoggingContext",
    "DebugUnifiedLoggingContext",
    "ConfigurationLoggingContext",
]

logger = getLogger("pibble")


class ColoredLoggingFormatter(Formatter):
    """
    An extension of the base logging.Formatter that colors the log
    depending on the level.

    This is using termcolor, so it's using terminal color escape sequences.
    These will appear as garbage bytes when not appropriately accounted for.
    """

    def format(self, record: LogRecord) -> str:
        """
        The main ``format`` function enumerates the six possible log levels
        into colors, and formats the log record with that color.

        :param record: The log record to format.
        :returns: The unicode string, colored if the log level is set.
        """
        formatted = super(ColoredLoggingFormatter, self).format(record)
        return {
            "CRITICAL": colored(formatted, "red", attrs=["reverse", "blink"]),
            "ERROR": colored(formatted, "red"),
            "WARNING": colored(formatted, "yellow"),
            "INFO": colored(formatted, "green"),
            "DEBUG": colored(formatted, "cyan"),
            "NOTSET": formatted,
        }[record.levelname.upper()]


class UnifiedLoggingContext:
    """
    A context manager that will remove logger handlers, then set the handler and level for the root
    logger to specified parameters.

    Will set logger variables back to their predefined values on exit.

    :param handler: The handler to set the root logger to.
    :param level: The log level.
    :param silenced: A list of any loggers to silence.
    """

    DEFAULT_FORMAT = (
        "%(asctime)s [%(name)s] %(levelname)s (%(filename)s:%(lineno)s) %(message)s"
    )

    def __init__(self, handler: Handler, level: int, silenced: List[str] = []):
        self.level = level
        self.handler = handler
        self.silenced = silenced

    def __enter__(self) -> None:
        self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()

    def start(self) -> None:
        """
        Find initialized loggers and set their level/handler.
        """
        self.handlers = {}
        self.levels = {}

        self.handlers["root"] = getLogger().handlers
        self.levels["root"] = getLogger().level

        getLogger().handlers = []
        getLogger().setLevel(self.level)

        for loggerName in Logger.manager.loggerDict:
            self.handlers[loggerName] = getLogger(loggerName).handlers
            self.levels[loggerName] = getLogger(loggerName).level

            getLogger(loggerName).handlers = []
            if loggerName in self.silenced:
                getLogger(loggerName).setLevel(99)
            else:
                getLogger(loggerName).setLevel(self.level)
                getLogger(loggerName).addHandler(self.handler)

        def print_http_client(*args: Any, **kwargs: Any) -> None:
            for line in (" ".join(args)).splitlines():
                getLogger("http.client").log(DEBUG, line)

        setattr(http.client, "print", print_http_client)
        http.client.HTTPConnection.debuglevel = 1

    def stop(self) -> None:
        """
        For loggers that were changed during start(), revert the changes.
        """
        getLogger().handlers = self.handlers["root"]
        getLogger().level = self.levels["root"]
        for loggerName in Logger.manager.loggerDict:
            if loggerName in self.handlers and loggerName in self.levels:
                getLogger(loggerName).handlers = self.handlers[loggerName]
                getLogger(loggerName).level = self.levels[loggerName]


class LevelUnifiedLoggingContext(UnifiedLoggingContext):
    """
    An extension of the UnifiedLoggingContext for use in debugging.

    :param level int: The log level.
    """

    def __init__(self, level: int, silenced: List[str] = []) -> None:
        self.level = level
        self.handler = StreamHandler(sys.stdout)
        self.handler.setFormatter(ColoredLoggingFormatter(self.DEFAULT_FORMAT))
        self.silenced = silenced


class DebugUnifiedLoggingContext(LevelUnifiedLoggingContext):
    """
    A shortand for LevelUnifiedLoggingContext(DEBUG)
    """

    def __init__(self, silenced: List[str] = []) -> None:
        super(DebugUnifiedLoggingContext, self).__init__(DEBUG, silenced)


class ConfigurationLoggingContext(UnifiedLoggingContext):
    """
    An extension of the UnifiedLoggingContext that reads an :class:`pibble.api.configuration.APIConfiguration` object.
    """

    def __init__(self, configuration: APIConfiguration, prefix: str = "logging."):
        self.level = configuration.get(f"{prefix}level", "CRITICAL").upper()
        self.silenced = configuration.get(f"{prefix}silenced", [])
        handler_class = configuration.get(f"{prefix}handler", "stream")
        if handler_class == "stream":
            stream = configuration.get(f"{prefix}stream", "stderr")
            if isinstance(stream, str):
                self.handler = StreamHandler(
                    sys.stdout if stream == "stdout" else sys.stderr
                )
            else:
                self.handler = StreamHandler(stream)
        elif handler_class == "file":
            file_path = configuration.get(f"{prefix}file", None)
            if file_path is None:
                raise ValueError(
                    f"Can't use 'file' handler without file - set {prefix}file"
                )
            if file_path.startswith("~"):
                file_path = os.path.expanduser(file_path)
            file_path = os.path.abspath(file_path)
            backup_count = configuration.get(f"{prefix}backups", 2)
            max_bytes = configuration.get(f"{prefix}maxbytes", 5 * 1024 * 1024)
            if not isinstance(backup_count, int):
                backup_count = 2
            if not isinstance(max_bytes, int):
                max_bytes = 5 * 1024 * 1024
            self.handler = RotatingFileHandler(
                file_path,
                mode="a",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding=None,
                delay=False,
            )
        elif handler_class == "syslog":
            self.handler = SysLogHandler(
                address=(
                    configuration["host"],
                    int(configuration["port"]),
                ),
                facility=configuration["facility"],
                socktype=socket.SOCK_DGRAM
                if configuration.get("protocol", "udp") == "udp"
                else socket.SOCK_STREAM,
            )
        else:
            raise KeyError("Unsupported handler class '{0}'.".format(handler_class))
        log_format = configuration.get(f"{prefix}format", self.DEFAULT_FORMAT)
        if configuration.get(f"{prefix}colored", configuration.get("color", False)):
            self.handler.setFormatter(ColoredLoggingFormatter(log_format))
        else:
            self.handler.setFormatter(Formatter(log_format))
