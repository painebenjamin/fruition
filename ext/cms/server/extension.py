from typing import Any

from pibble.util.log import logger
from pibble.util.helpers import url_join
from pibble.api.server.webservice.template.extensions import (
    StatementExtensionBase,
    FunctionExtensionBase,
)

__all__ = [
    "CMSExtensionStaticExtension",
    "CMSExtensionResolveStatementExtension",
    "CMSExtensionResolveFunctionExtension",
]


class CMSExtensionStaticExtension(StatementExtensionBase):
    """
    Allows for {% static var %} calls, that will resolve to the path to a server's
    static path.

    Example usage in a template::
      {% for script in scripts %}
        <script src="{% static script %}"></script>
      {% endfor %}

    """

    tags = {"static"}

    def __call__(self, *args: Any) -> str:
        if not args:
            raise ValueError("Path is required.")
        return url_join(self.getConfiguration()["server.cms.path.static"], str(args[0]))


class CMSExtensionResolveStatementExtension(StatementExtensionBase):
    """
    Provices access to the resolve() method on the server as a statement.

    This can be used as follows::
      <a href="{% resolve "Articles" %}">All Articles</a>

    """

    tags = {"resolve"}

    def __call__(self, *args: Any) -> str:
        if not args:
            raise ValueError("View name is required.")
        view = str(args[0])
        kwargs = args[1] if len(args) == 2 else {}
        logger.debug(
            "Resolving statement for view {0} with arguments {1}".format(view, kwargs)
        )
        if type(kwargs) is not dict:
            kwargs = {}
        server = self.getServer()
        if not hasattr(server, "resolve"):
            raise ValueError(
                "Server does not have resolve() method. Did you extend the right server base?"
            )
        return url_join(
            self.getConfiguration()["server.cms.path.root"],
            server.resolve(view, **kwargs),
        )


class CMSExtensionResolveFunctionExtension(FunctionExtensionBase):
    """
    Provices access to the resolve() method on the server as a function.

    This can be used as follows::
      {% for article in articles %}
        <a href="{{ resolve("Articles", id = article.id) }}">{{ article.name }}</a>
      {% endfor %}

    """

    name = "resolve"

    def __call__(self, *args: Any) -> str:
        if not args:
            raise ValueError("View name is required.")
        view = str(args[0])
        kwargs = args[1] if len(args) == 2 else {}
        logger.debug(
            "Resolving function for view {0} with arguments {1}".format(view, kwargs)
        )
        if type(kwargs) is not dict:
            kwargs = {}
        server = self.getServer()
        if not hasattr(server, "resolve"):
            raise ValueError(
                "Server does not have resolve() method. Did you extend the right server base?"
            )
        return url_join(
            self.getConfiguration()["server.cms.path.root"],
            server.resolve(str(view), **kwargs),
        )
