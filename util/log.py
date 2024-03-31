"""
Utilities for logging - the global logger, and contexts for debugging.
"""
from __future__ import annotations

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


pibble_static_handlers: List[Handler] = []
pibble_static_level: int = 99
pibble_is_frozen: bool = False

class FrozenLogger(Logger):
    """
    A logger that will not allow handlers to be added or removed.
    """
    @classmethod
    def from_logger(cls, logger: Logger) -> FrozenLogger:
        """
        Create a FrozenLogger from a Logger.
        """
        if not isinstance(logger, Logger):
            return logger # type: ignore
        new_logger = cls(logger.name, level=logger.level)
        new_logger.handlers = logger.handlers
        new_logger.propagate = logger.propagate
        new_logger.disabled = logger.disabled
        return new_logger

    def callHandlers(self, record: LogRecord) -> None:
        """
        Pass a record to all relevant handlers.
        This is a copy of the original callHandlers method, but with the
        handler list replaced with the static_handlers list when the logger is frozen.
        """
        global pibble_static_handlers, pibble_is_frozen, pibble_static_level
        from logging import lastResort, raiseExceptions
        c = self
        found = 0
        while c:
            for hdlr in pibble_static_handlers if pibble_is_frozen else c.handlers:
                found = found + 1
                if record.levelno >= pibble_static_level if pibble_is_frozen else hdlr.level:
                    hdlr.handle(record)
            if not c.propagate:
                c = None # type: ignore[assignment]
            else:
                c = c.parent # type: ignore[assignment]
        if (found == 0):
            if lastResort:
                if record.levelno >= lastResort.level:
                    lastResort.handle(record)
            elif raiseExceptions and not self.manager.emittedNoHandlerWarning:
                sys.stderr.write("No handlers could be found for logger"
                                 " \"%s\"\n" % self.name)
                self.manager.emittedNoHandlerWarning = True


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
        from logging import _acquireLock, _releaseLock, getLevelName # type: ignore[attr-defined]
        global pibble_static_handlers, pibble_static_level, pibble_is_frozen
        _acquireLock()
        # First freeze future loggers
        pibble_is_frozen = True
        pibble_static_handlers = [self.handler]
        if isinstance(self.level, int):
            pibble_static_level = self.level
        else:
            pibble_static_level = getLevelName(self.level) # type: ignore[unreachable]
        Logger.manager.setLoggerClass(FrozenLogger)

        # Now modify current loggers
        self.handlers = {}
        self.levels = {}
        self.propagates = {}

        self.handlers["root"] = Logger.root.handlers
        self.levels["root"] = Logger.root.level

        Logger.root.handlers = [self.handler]
        Logger.root.setLevel(self.level)

        for loggerName, logger in Logger.manager.loggerDict.items():
            if isinstance(logger, Logger):
                self.handlers[loggerName] = logger.handlers
                self.levels[loggerName] = logger.level
                self.propagates[loggerName] = logger.propagate
                logger.handlers = [self.handler]
                logger.propagate = False
                if loggerName in self.silenced:
                    logger.setLevel(99)
                else:
                    logger.setLevel(self.level)

        def print_http_client(*args: Any, **kwargs: Any) -> None:
            for line in (" ".join(args)).splitlines():
                getLogger("http.client").log(DEBUG, line)

        setattr(http.client, "print", print_http_client)
        http.client.HTTPConnection.debuglevel = 1
        _releaseLock()
        Logger.manager._clear_cache() # type: ignore[attr-defined]

    def stop(self) -> None:
        """
        For loggers that were changed during start(), revert the changes.
        """
        Logger.root.handlers = self.handlers["root"]
        Logger.root.level = self.levels["root"]
        for loggerName, logger in Logger.manager.loggerDict.items():
            if loggerName in self.handlers and loggerName in self.levels and loggerName in self.propagates and isinstance(logger, Logger):
                logger.handlers = self.handlers[loggerName]
                logger.level = self.levels[loggerName]
                logger.propagate = self.propagates[loggerName]
        Logger.manager.setLoggerClass(Logger)

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
