import os
from typing import Any, Union, List

from pibble.api.configuration import APIConfiguration
from pibble.api.helpers.store import APISessionStore, UnconfiguredAPISessionStore
from pibble.api.exceptions import ConfigurationError
from pibble.util.log import logger, ConfigurationLoggingContext
from pibble.util.strings import pretty_print, get_uuid


class APIBase:
    """
    A base class for servers and clients to inherit from.
    """

    session: Union[UnconfiguredAPISessionStore, APISessionStore]

    def __init__(self) -> None:
        logger.debug("Initializing API base.")
        self.configuration = APIConfiguration()
        self.configuration.put("session_key", get_uuid())
        self.session = UnconfiguredAPISessionStore()

    def on_configure(self) -> None:
        """
        Establishes session store, if able.

        Also configures logger and sets CWD.
        """
        if "logging" in self.configuration:
            context = ConfigurationLoggingContext(self.configuration)
            context.start()
            logger.debug("Established configured logger.")
        if "cwd" in self.configuration:
            cwd = self.configuration["cwd"]
            if "~" in cwd:
                cwd = os.path.expanduser(cwd)
            logger.debug(f"Changing to working directory {cwd}")
            os.chdir(cwd)
        if (
            isinstance(self.session, UnconfiguredAPISessionStore)
            and "session.store" in self.configuration
        ):
            logger.debug("Establishing configured session store.")
            self.session = APISessionStore(self.configuration)

    def destroy(self) -> None:
        """
        Destroys the API, clearing any state.
        """
        for cls in reversed(type(self).mro()):
            if hasattr(cls, "on_destroy") and "on_destroy" in cls.__dict__:
                try:
                    logger.debug(
                        "Destruction handler found for superclass {0}, executing.".format(
                            cls.__name__
                        )
                    )
                    cls.on_destroy(self)
                except Exception as ex:
                    raise ConfigurationError(str(ex))

    def configure(self, **configuration: Any) -> None:
        """
        Updates the configuration.

        :param configuration dict: Any number of configuration values to update.
        """
        self.configuration.update(**configuration)
        logger.debug(
            "Configuration updated on class {0}. Supers are {1}".format(
                type(self).__name__,
                pretty_print(*[cls.__name__ for cls in type(self).mro()]),
            )
        )
        for cls in reversed(type(self).mro()):
            if hasattr(cls, "on_configure") and "on_configure" in cls.__dict__:
                try:
                    logger.debug(
                        "Configuration update handler found for superclass {0}, executing.".format(
                            cls.__name__
                        )
                    )
                    cls.on_configure(self)
                except Exception as ex:
                    raise ConfigurationError(str(ex))

    def listMethods(self) -> List[str]:
        """
        Should be extended for function-based servers or clients.
        """
        raise NotImplementedError()
