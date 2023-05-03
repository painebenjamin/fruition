from __future__ import annotations

from re import compile, Pattern
from urllib.parse import unquote
from typing import Optional, Callable, Any, Type, Iterable, Union, List
from webob import Request, Response

from collections import defaultdict

from pibble.util.helpers import resolve
from pibble.util.log import logger
from pibble.api.exceptions import NotFoundError

from pibble.api.server.base import APIServerBase


class WebServiceAPIHandler:
    """
    Small class to hold handlers.
    """

    def __init__(
        self,
        function: Callable,
        pattern: Optional[Union[str, Pattern]] = None,
        methods: List[str] = [],
        bypass: List[Union[str, Type]] = [],
        reverse: Optional[tuple[str, str]] = None,
        format_response: bool = False,
        download_response: bool = False,
        cache_response: Optional[int] = None,
        compress_response: bool = False,
    ):
        self.function = function
        self.pattern = pattern
        self.methods = methods
        self.bypass = bypass
        self.reverse = reverse
        self.compress_response = compress_response
        self.format_response = format_response
        self.download_response = download_response
        self.cache_response = cache_response

    def get_pattern(self) -> Optional[Pattern]:
        if isinstance(self.pattern, str):
            return compile(self.pattern)
        return self.pattern

    def bind(self, **kwargs: Any) -> WebServiceAPIBoundHandler:
        return WebServiceAPIBoundHandler(self, **kwargs)

    def __repr__(self) -> str:
        return "{0} {1}: {2}{3}".format(
            ", ".join(self.methods),
            self.pattern,
            self.function.__name__,
            "" if not self.reverse else ", reverse: {0}".format(self.reverse),
        )

    def __call__(
        self,
        server: APIServerBase,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return self.function(server, request, response, *args, **kwargs)


class WebServiceAPIBoundHandler:
    """
    Binds a handler with URL arguments.
    """

    def __init__(self, handler: WebServiceAPIHandler, **kwargs: Any):
        self.handler = handler
        self.kwargs = kwargs

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.handler, attr)

    def __call__(
        self,
        server: APIServerBase,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return self.handler(
            server, request, response, *args, **{**kwargs, **self.kwargs}
        )


class WebServiceAPIHandlerRegistry:
    """
    A class for registering handlers.

    When extending the APIServerBase, you should define the `handlers` member of the class. Then, use `@handlers.path(<path>)` to use a regular expression match when a path is received in a request, and `@handler.methods(*methods)` to register it for HTTP methods. Any group dictionary members are also passed into the handler.

    Example ::

      class MyWebServiceAPI(APIServerBase):
        handlers = WebServiceAPIHandlerRegistry()

        @handlers.path("/")
        @handlers.methods("GET")
        def get_root(request, response):
          # Returns the root of the API
          pass

        @handlers.path("/user(/(?P<username>\w+))?")
        @handlers.methods("GET"):
        def get_user(request, response, username = None):
          # Handles getting either all users (username is None) or an individual user
          pass
    """

    handlers: List[WebServiceAPIHandler]

    def __init__(self) -> None:
        self.handlers = []

    def _find_handler_by_function(self, fn: Callable) -> WebServiceAPIHandler:
        """
        Retrieves a handler by a function.

        :param fn callable: The function to check for.
        :returns WebServiceAPIHandler: The handler to return.
        """
        for handler in self.handlers:
            if handler.function is fn:
                return handler
        raise NotFoundError(f"Cannot find function {fn}")

    def _find_handler_by_request(
        self, method: str, path: str
    ) -> Union[WebServiceAPIHandler, WebServiceAPIBoundHandler]:
        """
        Retrieves the handler matching a method and path.

        :param method str: The method - GET, PUT, POST, etc.
        :param path str: The request path.
        :returns WebServiceAPIHandler: The method that handles the request.
        """
        for handler in self.handlers:
            handler_pattern = handler.get_pattern()
            if handler_pattern is not None:
                match = handler_pattern.match(path)
                if match and method.upper() in handler.methods:
                    logger.debug(
                        "Handler {0} matched on path {1} and method {2}".format(
                            handler.function.__name__, path, method.upper()
                        )
                    )
                    groups = match.groupdict()
                    kwargs = dict(
                        [
                            (key, None if groups[key] is None else unquote(groups[key]))
                            for key in groups
                        ]
                    )
                    return handler.bind(**kwargs)
                elif match:
                    logger.debug(
                        "Handler {0} matched on path {1}, but not method {2}".format(
                            handler.function.__name__, path, method.upper()
                        )
                    )
                else:
                    logger.debug(
                        "Handler {0} did not match on path {1} (tried {2})".format(
                            handler.function.__name__, path, handler.pattern
                        )
                    )
        raise NotFoundError(
            "No handler found matching method {0} and path {1}.".format(
                method.upper(), path
            )
        )

    def create_handler(self, fn: Callable, **kwargs: Any) -> WebServiceAPIHandler:
        """
        Creates a handler.

        This can be overridden by extending classes to change behavior.
        """
        handler = WebServiceAPIHandler(fn, **kwargs)
        self.handlers.append(handler)
        return handler

    def modify_handler(self, fn: Callable, **kwargs: Any) -> WebServiceAPIHandler:
        """
        Modifies a handler.

        This can be overridden by extending classes to change behavior.
        """
        handler = self._find_handler_by_function(fn)
        if not handler:
            raise NotFoundError()
        for key in kwargs:
            setattr(handler, key, kwargs[key])
        return handler

    def create_or_modify_handler(
        self, fn: Callable, **kwargs: Any
    ) -> WebServiceAPIHandler:
        """
        Creates or modifies a handler.

        This can be overridden by extending classes to change behavior.
        """
        try:
            return self.modify_handler(fn, **kwargs)
        except NotFoundError:
            return self.create_handler(fn, **kwargs)

    def path(self, pattern: Union[str, Pattern]) -> Callable[[Callable], Callable]:
        """
        Registers a function with a path. Used as a decorator, should only pass one pattern, but it can be any valid regex pattern.

        Example usage ::

          handler = WebServiceAPIHandlerRegistry()

          @handler.path("/user(/(?P<username>\w+))?")
          def get_user(self, request, response, username = None):
            if username is None:
              # Get all users
            else:
              # Get one user

        :param pattern str: A regular expression pattern. Can be string or regular express (`r""`).
        :returns function: Returns the wrapper function. The inner wrapper function returns the function itself, so they can be composed.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(
                fn,
                pattern=pattern if isinstance(pattern, Pattern) else compile(pattern),
            )
            return fn

        return wrap

    def methods(self, *methods: Any) -> Callable[[Callable], Callable]:
        """
        Registers a function with any number of methods.

        Example usage::

          handler = WebServiceAPIHandlerRegistry()

          @handler.methods("PUT", "POST"):
          def make_user(self, request, response):
            # Make a user

        :param methods tuple: Any number of HTTP methods, all strings. Should be capitalized, like GET, PUT, POST, etc.
        :returns function: Returns the wrapper function. The inner wrapper function returns the function itself, so they can be composed.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(
                fn, methods=[method.upper() for method in methods]
            )
            return fn

        return wrap

    def format(self) -> Callable[[Callable], Callable]:
        """
        Indicates that the results of the request should be formatted by calling the format_response()
        handler. This, by default, is false.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, format_response=True)
            return fn

        return wrap

    def download(self) -> Callable[[Callable], Callable]:
        """
        Indicates that the results of the request is a file path, and that file path should be iterated
        over for the response in a streaming fashion.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, download_response=True)
            return fn

        return wrap

    def compress(self) -> Callable[[Callable], Callable]:
        """
        Indicates that the results of the request should be compressed (using zlib.)
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, compress_response=True)
            return fn

        return wrap

    def cache(
        self, cache_time: Optional[int] = 31536000
    ) -> Callable[[Callable], Callable]:
        """
        Indicates that the results of the request should be cacheed (using http headers.)
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, cache_response=cache_time)
            return fn

        return wrap

    def reverse(self, name: str, path: str = "/") -> Callable[[Callable], Callable]:
        """
        Registers a reverse() method for this URL.

        Calling handlers.resolve(name, **kwargs) will search for a handler with this name,
        and pass in **kwargs to the string formatter.

        Example usage::
          handlers = WebServiceAPIHandlerRegistry()

          @handlers.path("/article(/(?P<id>\d+))?$")
          @handlers.methods("GET")
          @handlers.reverse("Articles", "/article/{id}")
          def get_article(self, request, response, id = None):
            # returns one or all articles
            pass

          # Get URL for article 21
          article_url = handlers.resolve("Articles", id = 21) # /article/21

        Something worth mentioning is how the path is resolved. If, for instance,
        you have a multi-leveled path like "/article/{category}/{id}", then any
        variables not passed into a matching resolve() call will be filled with the
        empty string, and thus this path would result in "/article//". Trailing
        slashes are always stripped, so the resolve()'d url isn't so ugly.

        Example usage ::
          handlers = WebServiceAPIHandlerRegistry()

          @handlers.path("/article(?P<category>[a-zA-Z0-9_\-]+(/(?P<id>\d+))?)?$")
          @handlers.methods("GET")
          @handlers.reverse("Articles", "/article/{category}/{id}")
          def get_article(self, request, response, category = None, id = None):
            if category is not None and id is not None:
              # get article
            elif category is not None:
              # list articles in category
            else:
              # list categories

          news_url = handlers.resolve("Articles", category = "news") # /article/news
          article_url = handlers.resolve("Articles", category = "news", id = 21) # /article/news/21

        :param name str: The name of the string.
        :param path str: A formatting string.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, reverse=(name, path))
            return fn

        return wrap

    def bypass(self, *classes: Union[str, Type]) -> Callable[[Callable], Callable]:
        """
        Marks a handler to pybass parsing or preparing requests/responses.

        Example usage::

          handler = WebServiceAPIHandlerRegistry()

          @handler.path("/insecure")
          @handler.bypass("BasicAuthenticationMiddleware")
          def insecure_endpoint(self, request, response):
            # Handle an insecure request

        :param classes tuple: Any number of class names to ignore. These can be fully qualified strings, like `pibble.api.middleware.webservice.authentication.basic.BasicAuthenticationMiddleware` or an actual class.
        :returns function: Returns the wrapper function.
        """
        classlist = [cls if isinstance(cls, type) else resolve(cls) for cls in classes]

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, bypass=classlist)
            return fn

        return wrap

    def resolve(self, view_name: str, **kwargs: Any) -> str:
        """
        Resolves a URL name with URL arguments defined by **kwargs. See reverse() above
        for more details.

        :see
        :param name str: The name of the view to find.
        :param kwargs dict: Any number of URL arguments to pass in.
        """
        for handler in self.handlers:
            if handler.reverse is not None and handler.reverse[0] == view_name:
                format_dict = defaultdict(lambda: "")  # type: ignore
                format_dict.update(kwargs)
                resolved = handler.reverse[1].format_map(format_dict)
                while resolved.find("//") != -1:
                    resolved = resolved.replace("//", "/")
                while resolved and resolved[-1] == "/":
                    resolved = resolved[:-1]
                if not resolved:
                    return "/"
                return resolved
        raise NotFoundError("No view with name {0}".format(view_name))

    def __iter__(self) -> Iterable[WebServiceAPIHandler]:
        self.index = 0
        while True:
            try:
                yield next(self)
            except StopIteration:
                return

    def __next__(self) -> WebServiceAPIHandler:
        if self.index >= len(self.handlers):
            raise StopIteration()
        result = self.handlers[self.index]
        self.index += 1
        return result

    def __call__(
        self,
        method: str,
        path: str,
        server: APIServerBase,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Calls the actual handler function.

        :param method str: The method - GET, PUT, POST, etc.
        :param path str: The request path.
        :param server pibble.api.server.base.APIServerBase: The implementing server.
        :param args tuple: The arg array.
        :param kwargs dict: The kwargs dict.
        :returns object: The response from the handler.
        """
        return self._find_handler_by_request(method, path)(server, *args, **kwargs)

    def __repr__(self) -> str:
        """
        Stringify the handlers for debugging purposes.
        """
        return "\n".join([str(handler) for handler in self.handlers])
