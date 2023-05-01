from __future__ import annotations

import os

from pibble.util.files import load_yaml, load_json
from pibble.util.strings import Serializer

from pibble.api.configuration import APIConfiguration
from pibble.api.meta.base import MetaService, MetaFunction

__all__ = ["MetaFactory"]


class MetaFactory:
    """
    A class to hold configuration values and create services.

    :param configuration_file str: The configuration file to read.
    :raises TypeError: When the configuration file is in an unsupported format.
    :raises KeyError: When the configuration file is malformed.
    :raises IOError: When there is an issue reading the configuration file.
    """

    def __init__(self, configuration: dict):
        if "configuration" not in configuration:
            raise KeyError("Missing keyword 'configuration.'")

        self.configuration = Serializer.deserialize(configuration)
        if "cwd" not in self.configuration:
            self.configuration["cwd"] = os.getcwd()
        self.api_configuration = APIConfiguration(**self.configuration["configuration"])

    @staticmethod
    def from_file(configuration_file: str) -> MetaFactory:
        """
        Loads a file instead of using a dict.
        """
        if configuration_file.endswith(".yaml") or configuration_file.endswith(".yml"):
            configuration = load_yaml(configuration_file)
        elif configuration_file.endswith(".json"):
            configuration = load_json(configuration_file)
        else:
            raise TypeError(
                "Unsupported configuration file '{0}'.".format(configuration_file)
            )
        if type(configuration) is not dict:
            raise TypeError(
                f"Bad configuration file {configuration_file} - must evaluate to a dictionary."
            )
        return MetaFactory(configuration)

    def __call__(self, scope: str) -> MetaService:
        if scope not in self.configuration["configuration"]:
            raise KeyError("Missing configuration for scope '{0}'.".format(scope))

        if "classes" not in self.configuration["configuration"][scope]:
            raise KeyError("Configuration missing keyword '{0}.classes'.".format(scope))

        functions = dict(
            [
                (
                    str(function["name"]),
                    MetaFunction(
                        function["language"],
                        function["script"],
                        function.get("register", False),
                    ),
                )
                for function in self.configuration["configuration"][scope].get(
                    "functions", []
                )
            ]
        )

        service = MetaService(
            self.configuration.get("name", "MetaService"),
            self.configuration["configuration"][scope]["classes"],
            self.configuration["configuration"],
            functions,
        )

        return service
