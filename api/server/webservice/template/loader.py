import os
import jinja2

from jinja2.ext import Extension
from typing import Optional, Callable, Any, Type, Union, Dict

from pibble.api.exceptions import ConfigurationError
from pibble.api.configuration import APIConfiguration
from pibble.api.base import APIBase

from pibble.util.log import logger
from pibble.util.helpers import resolve

from pibble.api.server.webservice.template.extensions import (
    TestExtensionBase,
    FilterExtensionBase,
    FunctionExtensionBase,
)


class TemplateLoader:
    """
    This is a simple loader that will use jinja2 to create an environment
    with file system loaders and extensions.

    A simple example:

    >>> from pibble.api.configuration import APIConfiguration
    >>> from pibble.api.server.webservice.template.loader import TemplateLoader
    >>> test_template = "{{ var }}"
    >>> configuration = APIConfiguration(**{"server": {"template": {"static": {"test": test_template}}}})
    >>> loader = TemplateLoader(configuration)
    >>> loader.render("test", var = 5)
    '5'

    A more complex one using example extensions:

    >>> from pibble.api.configuration import APIConfiguration
    >>> from pibble.api.server.webservice.template.loader import TemplateLoader
    >>> from pibble.api.server.webservice.template.extensions import ExampleContextExtension
    >>> from pibble.api.server.webservice.template.extensions import ExampleStatementExtension
    >>> from pibble.api.server.webservice.template.extensions import ExampleTestExtension
    >>> from pibble.api.server.webservice.template.extensions import ExampleFilterExtension
    >>> from pibble.api.server.webservice.template.extensions import ExampleFunctionExtension
    >>> test_template = "{% example_statement 5 %}{% example_context %}foo{% endexample_context %}{{ square(var)|square }}{% if var is prime %}prime{% endif %}"
    >>> test_extensions = [ExampleContextExtension, ExampleStatementExtension, ExampleTestExtension, ExampleFilterExtension, ExampleFunctionExtension]
    >>> configuration = APIConfiguration(**{"server": {"template": {"extensions": test_extensions, "static": {"test": test_template}}}})
    >>> loader = TemplateLoader(configuration)
    >>> loader.render("test", var = 3)
    'xxxxxFOO81prime'

    All configuration is optional.
    - `server.template.directories` Either a single or list of directories to look for template files in.
    - `server.template.static` A static dictionary of (template_name, template_string).
    - `server.template.extensions` A list of string fully-qualified names or types. See `pibble.api.server.webservice.html.template.extensions`.
    """

    def __init__(
        self, configuration: APIConfiguration, server: Optional[APIBase] = None
    ):
        self.configuration = configuration
        self.server = server

        self.directories = self.configuration.get(
            "server.template.directories", [os.getcwd()]
        )
        if not isinstance(self.directories, list):
            self.directories = [self.directories]
        if self.configuration.get("server.template.recurse", False):
            self.directories = [
                directory
                for template_directory in self.directories
                for directory, subdirectory, filenames in os.walk(template_directory)
            ]

        self.extensions = self.configuration.get("server.template.extensions", [])
        if not isinstance(self.extensions, list):
            self.extensions = [self.extensions]

        self.static = self.configuration.get("server.template.static", {})

        # Resolve all extensions
        self.extensions = [
            extension if isinstance(extension, type) else resolve(extension)
            for extension in self.extensions
        ]

        # Add in Lambdas

        lambdas: Dict[str, Callable] = {}
        lambdas["getServer"] = lambda *args: self.server
        lambdas["getConfiguration"] = lambda *args: self.configuration

        self.extensions = [
            type("{0}Extension".format(extension.__name__), (extension,), lambdas)
            for extension in self.extensions
        ]

        # Filter out ones that needs to be assigned later

        self.tests = [
            extension
            for extension in self.extensions
            if issubclass(extension, TestExtensionBase)
        ]
        self.filters = [
            extension
            for extension in self.extensions
            if issubclass(extension, FilterExtensionBase)
        ]
        self.functions = [
            extension
            for extension in self.extensions
            if issubclass(extension, FunctionExtensionBase)
        ]
        self.extensions = [
            extension
            for extension in self.extensions
            if issubclass(extension, Extension)
        ]

        self.loader = jinja2.ChoiceLoader(
            [jinja2.DictLoader(self.static), jinja2.FileSystemLoader(self.directories)]
        )
        self.environment = jinja2.Environment(
            extensions=self.extensions, loader=self.loader
        )

        # Assign later extensions
        for assignable_extension_type in [self.tests, self.filters, self.functions]:
            for assignable_extension in assignable_extension_type:
                assignable_extension.assign(self.environment)

    def extend(
        self,
        *extensions: Union[
            Type[TestExtensionBase],
            Type[FilterExtensionBase],
            Type[FunctionExtensionBase],
            Type[Extension],
        ]
    ) -> None:
        """
        Adds an extension after initial creation.

        :param extensions list<Extension>: Either a jinja2.ext.Extension or any of the extensions in the template extension directory.
        """
        lambdas: Dict[str, Callable] = {}
        lambdas["getServer"] = lambda *args: self.server
        lambdas["getConfiguration"] = lambda *args: self.configuration
        for extension in extensions:
            extension = type(
                "{0}Extension".format(extension.__name__), (extension,), lambdas
            )

            if issubclass(extension, TestExtensionBase):
                if extension in self.tests:
                    logger.debug(
                        "Tried to extend template loader with duplicate test {0}".format(
                            extension
                        )
                    )
                    return
                logger.debug("Template loader adding test {0}".format(extension))
                self.tests.append(extension)
                extension.assign(self.environment)
            elif issubclass(extension, FilterExtensionBase):
                if extension in self.filters:
                    logger.debug(
                        "Tried to extend template loader with duplicate filter {0}".format(
                            extension
                        )
                    )
                    return
                logger.debug("Template loader adding filter {0}".format(extension))
                self.filters.append(extension)
                extension.assign(self.environment)
            elif issubclass(extension, FunctionExtensionBase):
                if extension in self.functions:
                    logger.debug(
                        "Tried to extend template loader with duplicate function {0}".format(
                            extension
                        )
                    )
                    return
                logger.debug("Template loader adding function {0}".format(extension))
                self.functions.append(extension)
                extension.assign(self.environment)
            elif issubclass(extension, Extension):
                if extension in self.extensions:
                    logger.debug(
                        "Tried to extend template loader with duplicate extension {0}".format(
                            extension
                        )
                    )
                    return
                logger.debug("Template loader adding extension {0}".format(extension))
                self.extensions.append(extension)
                self.environment.add_extension(extension)
            else:
                raise ConfigurationError(
                    "Extension does not extend either a base or assignable Jinja2 extension."
                )

    def render(self, name: str, template: Optional[bool] = True, **context: Any) -> str:
        """
        Renders a template name with optional context.

        :param name str: The name (path) of the template to render.
        :param context dict: A dictionary of context to pass into the template.
        :returns str: The rendered content.
        :raises TemplateNotFoundException: When the template is not found by the loader.
        """
        try:
            if not template:
                return self.environment.from_string(name).render(**context)
            return self.environment.get_template(name).render(**context)
        except jinja2.exceptions.TemplateNotFound:
            raise ConfigurationError(
                "Couldn't find template {0}. Tried:\r\n{1}".format(
                    name,
                    "\r\n".join(
                        [
                            "{0:d}: {1:s}{2:s}".format(
                                i + 1,
                                directory,
                                ""
                                if os.path.isdir(directory)
                                else " (NOT FOUND/PERMISSION ERROR)",
                            )
                            for i, directory in enumerate(self.directories)
                        ]
                    ),
                )
            )
