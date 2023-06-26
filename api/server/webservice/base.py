from __future__ import annotations

import io
import os
import logging
import mimetypes

from traceback import format_exc

from typing import (
    Optional,
    Any,
    Callable,
    Type,
    Tuple,
    Union,
    List,
    Dict,
    cast,
    TYPE_CHECKING,
)

from webob import Request, Response

from pibble.util.strings import decode
from pibble.util.log import logger
from pibble.util.helpers import CompressedIterator
from pibble.util.files import FileIterator
from pibble.api.server.base import APIServerBase
from pibble.api.server.webservice.handler import (
    WebServiceAPIHandlerRegistry,
    WebServiceAPIHandler,
    WebServiceAPIBoundHandler,
)
from pibble.api.middleware.webservice.base import WebServiceAPIMiddlewareBase

from pibble.api.exceptions import (
    BadRequestError,
    BadResponseError,
    NotFoundError,
    UnsupportedMethodError,
    AuthenticationError,
    PermissionError,
    ConfigurationError,
    StateConflictError,
    TooManyRequestsError,
)

from pibble.api.helpers.wrappers import (
    RequestWrapper,
    ResponseWrapper,
)

if TYPE_CHECKING:
    # If TYPE_CHECKING evaluates to true, then we're reviewing this code
    # in a typechecking fashion (i.e. via mypy). This means some packages
    # are available that are not usually available, like _typeshed.
    #
    # Since we called 'from __future__ import annotations' at the top, we're
    # able to use these classes as annotations **at any time**, even when they
    # wouldn't be available at runtime. That means these are all valid
    # type to notate, and will be appropriately checked when necessary. Neat!
    from _typeshed.wsgi import StartResponse, WSGIEnvironment, WSGIApplication


class WebServiceAPIServerBase(APIServerBase):
    """
    A web service API base, useful for extension or mixins.

    To add functionality to the web service, use a :class:`pibble.api.server.webservice.handler.WebServiceAPIHandlerRegistry` to register methods and paths.
    """

    HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE,PATCH,OPTIONS,HEAD",
        "Access-Control-Expose-Headers": "Access-Control-Allow-Origin",
        "Access-Control-Allow-Headers": "Origin,X-Requested-Width,Content-Type,Accept,Authorization,X-CSRFToken,X-API-Key",
    }

    EXCEPTION_CODES = {
        BadRequestError: 400,
        AuthenticationError: 401,
        PermissionError: 403,
        NotFoundError: 404,
        UnsupportedMethodError: 405,
        StateConflictError: 409,
        TooManyRequestsError: 429,
        NotImplementedError: 501,
    }

    class_handlers: List[WebServiceAPIHandlerRegistry]

    def __init__(self) -> None:
        super(WebServiceAPIServerBase, self).__init__()
        self.class_handlers = []

    def on_configure(self) -> None:
        """
        On configuration, register handlers.
        """
        self.register_all_handlers()

    def format_exception(
        self,
        exception: Exception,
        request: Union[Request, RequestWrapper],
        response: Union[Response, ResponseWrapper],
    ) -> str:
        """
        Formats an exception. The base class only stringifies this; implementing classes should put in their appropriate formats.

        :param exception exception: The exception thrown.
        """
        return str(exception)

    def format_response(
        self,
        result: Any,
        request: Union[Request, RequestWrapper],
        response: Union[Response, ResponseWrapper],
    ) -> str:
        """
        Formats a response. The base class stringifies this.

        This is from when a handler returns something, and indicates it wants the server to format it.
        """
        return str(result)

    def register_all_handlers(self) -> None:
        """
        Runs all ``register_handlers()`` methods.

        Used for middleware that registers handlers.
        """
        for cls in reversed(type(self).mro()):
            cls_mro = cls.mro()
            if (
                WebServiceAPIServerBase in cls_mro
                or WebServiceAPIMiddlewareBase in cls_mro
            ):
                if hasattr(cls, "get_handlers") and "get_handlers" in cls.__dict__:
                    logger.debug(
                        "Registering handlers in class {0} with 'get_handlers()'".format(
                            cls.__name__
                        )
                    )
                    self.class_handlers.append(cls.get_handlers())
                elif hasattr(cls, "handlers") and "handlers" in cls.__dict__:
                    logger.debug(
                        "Registering handlers in class {0} with 'handlers'".format(
                            cls.__name__
                        )
                    )
                    self.class_handlers.append(cls.handlers)

    def prepare_all(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
        handler: Optional[
            Union[WebServiceAPIHandler, WebServiceAPIBoundHandler]
        ] = None,
    ) -> None:
        """
        Runs all ``prepare()`` methods.

        :param request Request: The request before processing.
        :param response Response: The response before processing.
        """
        for cls in reversed(type(self).mro()):
            if hasattr(cls, "prepare") and "prepare" in cls.__dict__:
                if handler is None or (
                    handler is not None and cls not in handler.bypass
                ):
                    logger.debug(
                        "Preparing request/response in class {0}".format(cls.__name__)
                    )
                    cls.prepare(self, request, response)

    def parse_all(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
        handler: Optional[
            Union[WebServiceAPIHandler, WebServiceAPIBoundHandler]
        ] = None,
    ) -> None:
        """
        Runs all ``parse()`` methods.

        :param request Request: The request after processing.
        :param response Response: The response after processing.
        """
        for cls in reversed(type(self).mro()):
            if hasattr(cls, "parse") and "parse" in cls.__dict__:
                if handler is None or (
                    handler is not None and cls not in handler.bypass
                ):
                    logger.debug(
                        "Parsing request/response in class {0}".format(cls.__name__)
                    )
                    cls.parse(self, request, response)

    def resolve(self, view_name: str, **kwargs: Any) -> str:
        """
        Finds a handler by the view name.

        :param view_name str: The view name to find.
        :returns str: The resolved path.
        :raises NotFoundError: When no handlers are found,
        """

        path = None
        last_error = None
        tried_handlers = []

        for handlers in self.class_handlers:
            tried_handlers.append(handlers)
            try:
                path = handlers.resolve(view_name, **kwargs)
                break
            except NotFoundError as ex:
                continue

        if not path:
            raise NotFoundError(
                f"No view with name {view_name} (tried {tried_handlers})"
            )
        return path

    def _find_handler_by_request(
        self, request: Union[Request, RequestWrapper]
    ) -> Union[WebServiceAPIHandler, WebServiceAPIBoundHandler]:
        """
        Finds a handler by the request object.

        Will iterate through handlers in method resolution order to find the highest priority
        handler that matches a given a request, based on whatever criteria the handler
        has.

        :param request Request: A webob.Request.
        :returns WebServiceAPIHandler: The handler found.
        :raises NotFoundError: When no handers are found.
        """
        handler = None
        last_error = None
        method = request.method
        path = request.path
        root = self.configuration.get("server.root", "")
        if path.startswith(root):
            path = path[len(root) :]
        else:
            logger.warning(
                f"Request path {path} does not begin with server root {root}. This is likely a misconfiguration."
            )

        for handlers in self.class_handlers:
            try:
                handler = handlers._find_handler_by_request(method, path)
                break
            except NotFoundError as ex:
                last_error = ex
                continue

        if handler is None:
            if last_error is None:
                raise NotFoundError("No handlers registered.")
            raise cast(Exception, last_error)
        return handler

    def redirect(
        self, response: Union[Response, ResponseWrapper], location: str, code: int = 301
    ) -> None:
        """
        Issues a redirect response.
        """
        response.status_code = code
        response.location = location

    def handle_request(
        self,
        request: Union[Request, RequestWrapper],
        response: Union[Response, ResponseWrapper],
    ) -> Union[Response, ResponseWrapper]:
        """
        Given a request, this will find the appropriate handler, execute
        its method, and put the response into the provided response object.

        :param request Request: A webob.Request or RequestWrapper
        :param response Response: A webob.Response or ResponseWarpper
        :returns:
        """
        headers = {
            **WebServiceAPIServerBase.HEADERS,
            **getattr(self, "headers", {}),
        }
        for header_name in headers:
            response.headers[header_name] = headers[header_name]
        handler = None
        response.status_code = 200
        if request.method != "OPTIONS":
            try:
                accepted_encodings = request.headers.get("Accept-Encoding", "")
                handler = self._find_handler_by_request(request)
                self.parse_all(request, response, handler)
                result = handler(self, request, response)
                if handler.cache_response:
                    response.headers["Cache-Control"] = "max-age={0}".format(
                        handler.cache_response
                    )
                if handler.download_response:
                    # Check to see if we can compress.
                    if isinstance(result, io.IOBase):
                        if "gzip" in accepted_encodings and handler.compress_response:
                            # Compress the result itearatively.
                            logger.debug("Iteratively compressing IO-based result.")
                            response.app_iter = CompressedIterator(result)
                            response.headers["Content-Encoding"] = "gzip"
                        else:
                            # The result of seek() is the byte offset of the IO handle. The first argument is the byte offset, and the second offset is the enum for the origin of the offset.
                            # So, by calling seek(0, 2), we get the byte length of the IO handle (2 indicates the offset is from the end of the stream.)
                            # We then call seek(0) to go back to 0 bytes from the beginning so webob can read the whole stream for the response.
                            response.content_length = result.seek(0, 2)
                            result.seek(0)
                            response.app_iter = result
                    elif isinstance(result, str) or isinstance(result, bytes):
                        # mimetypes module guesses based on the file extension, and returns an array of types and confidence intervals.
                        # We take the first one since it's the most likely.
                        # In the case there is no result (like if the file has no extension), the module returns [None], and we won't set response.content_type.
                        # The handler can still set content_type itself.
                        if isinstance(result, bytes):
                            result = decode(result)
                        response.content_type = mimetypes.guess_type(result)[0]
                        # Pass through the basename of the file.
                        response.headers[
                            "Content-Disposition"
                        ] = 'inline; filename="{0}"'.format(os.path.basename(result))
                        iterable = FileIterator(
                            result,
                            self.configuration.get("server.chunksize", 4096),
                        )
                        if "gzip" in accepted_encodings and handler.compress_response:
                            # Compress the result iteratively
                            logger.debug("Iteratively compressing file-based result.")
                            response.app_iter = CompressedIterator(iterable)
                            response.headers["Content-Encoding"] = "gzip"
                        else:
                            # This is a file path, we can easily query the FS for the size.
                            response.content_length = os.path.getsize(result)
                            response.app_iter = iterable
                    else:
                        raise BadResponseError(
                            "Handler should have returned either a file path or io.IOBase, got {0} instead.".format(
                                type(result).__name__
                            )
                        )
                else:
                    if handler.format_response:
                        logger.debug(
                            "Handler indicates response should be formatted, calling highest priority format method."
                        )
                        result = self.format_response(
                            result=result, request=request, response=response
                        )
                    if "gzip" in accepted_encodings and handler.compress_response:
                        logger.debug("Compressing unicode result.")
                        response.headers["Content-Encoding"] = "gzip"
                        if isinstance(result, str):
                            result = result.encode("utf-8")
                        elif not isinstance(result, bytes):
                            result = str(result).encode("utf-8")
                        response.app_iter = CompressedIterator(io.BytesIO(result))
                    elif isinstance(result, str):
                        response.text = result
                    elif isinstance(result, bytes):
                        response.body = result
            except (
                PermissionError,
                AuthenticationError,
                NotFoundError,
                UnsupportedMethodError,
                NotImplementedError,
                BadRequestError,
                TooManyRequestsError,
                StateConflictError,
            ) as ex:
                logger.warning(
                    "Received exception in handler: {0}({1})".format(
                        type(ex).__name__, str(ex)
                    )
                )
                logger.debug(format_exc())
                error_code = 500
                for error_class in self.EXCEPTION_CODES:
                    if isinstance(ex, error_class):
                        error_code = self.EXCEPTION_CODES[error_class]
                        break
                response.status_code = error_code
                response.text = self.format_exception(
                    exception=ex, request=request, response=response
                )
            except Exception as ex:
                logger.error(
                    "Unexpected exception in application: {0}() {1}".format(
                        type(ex).__name__, str(ex)
                    )
                )
                logger.debug(format_exc())
                response.status_code = 500
                response.text = self.format_exception(
                    exception=ex, request=request, response=response
                )
        self.prepare_all(request, response, handler)
        if logger.level == logging.DEBUG:
            logger.debug("Sending headers:")
            for header_name in response.headers:
                logger.debug(
                    "{0}: {1}".format(header_name, response.headers[header_name])
                )
        return response

    def wsgi(self) -> WSGIApplication:
        """
        Returns an "application" function, almost all wsgi servers expect this.

        :return function: The application to pass into your wsgi server of choice.
        """

        def application(environ: WSGIEnvironment, start_response: StartResponse) -> Any:
            try:
                request = Request(environ)
                response = Response()
                self.handle_request(request, response)
                return response(environ, start_response)
            except Exception as ex:
                logger.error(
                    "Unhandled exception in application, no response will be sent: {0}() {1}".format(
                        type(ex).__name__, str(ex)
                    )
                )
                logger.debug(format_exc())
                raise ex

        return application

    def serve(self, destroy_on_stop: bool = True) -> None:
        """
        Serves the API through varying means.

        This is provided as a shortcut option, and not intended for use in production.
        """
        try:
            driver = self.configuration["server.driver"]
            host = self.configuration["server.host"]
            port = int(self.configuration["server.port"])
            secure = self.configuration.get("server.secure", False)
            cert = self.configuration.get("server.cert", None)
            key = self.configuration.get("server.key", None)
            chain = self.configuration.get("server.chain", None)
            workers = self.configuration.get("server.workers", None)

            logger.debug(
                "Attempting to run development server process using driver {0} on {1}://{2}:{3}.".format(
                    driver, "https" if secure else "http", host, port
                )
            )

            run_driver: Optional[Callable] = None

            if driver == "cherrypy":
                from pibble.api.server.webservice.drivers.driver_cherrypy import (
                    run_cherrypy,
                )

                destroy_on_stop = False
                run_driver = run_cherrypy
            elif driver == "werkzeug":
                from pibble.api.server.webservice.drivers.driver_werkzeug import (
                    run_werkzeug,
                )

                run_driver = run_werkzeug
            elif driver == "gunicorn":
                from pibble.api.server.webservice.drivers.driver_gunicorn import (
                    run_gunicorn,
                )

                run_driver = run_gunicorn

            if run_driver is None:
                raise ConfigurationError(
                    "Server driver {0} not supported.".format(driver)
                )
            run_driver(self, host, port, secure, cert, key, chain, workers)
        except KeyError as ex:
            raise ConfigurationError(str(ex))
        finally:
            if destroy_on_stop:
                self.destroy()


class MethodBasedWebServiceAPIServerBase(WebServiceAPIServerBase):
    """
    A base class for method-based servers, i.e. RPC and SOAP.

    This handles storing methods and allows for some nice and easy-to-use syntax for
    implementing servers.
    """

    methods: List[MethodBasedWebServiceAPIServerBase.WebServiceMethod]

    def __init__(self) -> None:
        super(MethodBasedWebServiceAPIServerBase, self).__init__()
        self.methods = []

    def _find_method_by_function(
        self, fn: Callable
    ) -> Optional[MethodBasedWebServiceAPIServerBase.WebServiceMethod]:
        """
        Finds a method by the function.

        Uses the "is" operator to ensure memory-space equivalence.
        """
        filtered_methods = [method for method in self.methods if method.method is fn]
        if not filtered_methods:
            return None
        return filtered_methods[0]

    def _find_method_by_name(
        self, name: str
    ) -> Optional[MethodBasedWebServiceAPIServerBase.WebServiceMethod]:
        """
        Finds a method by its name.

        Will use either ``fn.__name__``, or the supplied name.
        """
        filtered_methods = [method for method in self.methods if method.name == name]
        if not filtered_methods:
            return None
        return filtered_methods[0]

    def register(self, *args: Union[str, Callable]) -> Callable[[Callable], Callable]:
        """
        Registers a function.

        This is usable in two different forms, either directly called from the instance, or as a decorator.

        Decorator examples::

          # Uses fn.__name__
          @server.register
          def my_function(*args)
            pass

          # With a custom name
          @server.register("my_other_name")
          def my_function(*args)
            pass

        Instance examples::

          def my_function(*args):
            pass

          # Uses fn.__name__
          server.register(my_function)

          # With a custom name
          server.register("my_other_name")(my_function)

        :raises KeyError: When a function is already registered, or a name is already taken.
        """

        def wrap(method: Callable) -> Callable:
            try:
                name = getattr(wrap, "name", None)
                if name is None:
                    name = getattr(method, "__name__")
                if name is None:
                    raise ConfigurationError(
                        "Can't get name for method {0}".format(method)
                    )
                fn = self._find_method_by_function(method)
                if fn is None:
                    if any([m.name == name and m.registered for m in self.methods]):
                        raise KeyError(
                            "A function named '{0}' is already registered.".format(name)
                        )
                    self.methods.append(
                        MethodBasedWebServiceAPIServerBase.WebServiceMethod(
                            method, name, method.__doc__, [], None, True, None, None
                        )
                    )
                elif fn.registered:
                    raise KeyError("Function '{0}' is already registered.".format(name))
                else:
                    fn.name = name
                    fn.registered = True
                return method
            except Exception as ex:
                raise ConfigurationError(
                    "Received exception when registering method. {0}: {1}".format(
                        type(ex).__name__, ex
                    )
                )

        if len(args) == 1 and (isinstance(args[0], str) or isinstance(args[0], bytes)):
            setattr(wrap, "name", args[0])
            return wrap
        else:
            method = cast(Callable, args[0])
            return wrap(method)

    def sign_response(
        self, *args: Union[Type, Callable]
    ) -> Callable[[Callable], Callable]:
        """
        Signs the response type of a method.

        This is usable in two different forms, either directly called from the instance, or as a decorator.

        Decorator examples::

          @server.sign_response(int)
          def add(a, b):
            return a + b

          @server.sign_response(list):
          def fib(n):
            def generate():
              i = 0
              a, b = 0, 1
              while i < n:
                yield a
                a, b = b, a + b
                i += 1
            return list(generate())


        Instance examples::

          def add(a, b):
            return a + b

          server.sign_response(int)(add)

        :raises TypeError: When a signatures contains None.
        """

        def wrap(method: Callable) -> Callable:
            signature = getattr(wrap, "signature", None)
            if signature is None:
                raise TypeError("Cannot sign a response with a NoneType result.")
            fn = self._find_method_by_function(method)
            if fn is None:
                self.methods.append(
                    MethodBasedWebServiceAPIServerBase.WebServiceMethod(
                        method,
                        method.__name__,
                        method.__doc__,
                        [],
                        signature,
                        False,
                        None,
                        None,
                    )
                )
            else:
                fn.response_signature = signature
            return method

        setattr(wrap, "signature", args[0])
        return wrap

    def sign_request(
        self, *args: Union[Type, Callable]
    ) -> Callable[[Callable], Callable]:
        """
        Signs the request type of a method. Can be called multiple times for multiple signatures.

        This is usable in two different forms, either directly called from the instance, or as a decorator.

        Decorator example::

          @server.sign_request(int, int)
          def add(a, b):
            return a + b

        Instance example:

          def add(a, b):
            return a + b

          server.sign_request(int, int)(add)

        :raises TypeError: When a signatures contains None.
        """

        def wrap(method: Callable) -> Callable:
            signature = [t for t in wrap.signature if isinstance(t, type)]  # type: ignore
            if any([s is None for s in signature]):
                raise TypeError("Cannot sign a request with a NoneType parameter.")
            fn = self._find_method_by_function(method)
            if fn is None:
                self.methods.append(
                    MethodBasedWebServiceAPIServerBase.WebServiceMethod(
                        method,
                        method.__name__,
                        method.__doc__,
                        [list(signature)],
                        None,
                        False,
                        None,
                        None,
                    )
                )
            else:
                fn.signature.append(list(signature))  # type: ignore
            return method

        setattr(wrap, "signature", args)
        return wrap

    def sign_named_response(self, **kwargs: Any) -> Callable[[Callable], Callable]:
        """
        Signs the response type of a method, when the response takes an object instead of an array.

        The keyword argument must contain either a type or a value. If it's a type, it's required, if it's a value, it's not.

        Decorator example::

          @server.sign_named_request(base = int, exponent = 2)
          @server.sign_named_response(base = int, exponent = int, value = int)
          def pow(base, exponent = 2):
            return {
              "base": base,
              "exponent": exponent,
              "value": base ** exponent
            }

        Instance example::

          def pow(base, exponent = 2):
            return {
              "base": base,
              "exponent": exponent,
              "value": base ** exponent
            }

          server.sign_named_request(base = int, exponent = 2)(pow)
          server.sign_named_response(base = int, exponent = int, value = int)(pow)
        """

        def wrap(method: Callable) -> Callable:
            signature = getattr(wrap, "signature", None)
            fn = self._find_method_by_function(method)
            if fn is None:
                self.methods.append(
                    MethodBasedWebServiceAPIServerBase.WebServiceMethod(
                        method,
                        method.__name__,
                        method.__doc__,
                        None,
                        None,
                        False,
                        None,
                        signature,
                    )
                )
            else:
                fn.response_named_signature = kwargs
            return method

        setattr(wrap, "signature", kwargs)
        return wrap

    def sign_named_request(self, **kwargs: Any) -> Callable[[Callable], Callable]:
        """
        Signs the request type of a method, when the request takes an object instead of an array.

        The keyword argument must contain either a type or a value. If it's a type, it's required, if it's a value, it's not.

        Decorator example::

          @server.sign_named_request(base = int, exponent = 2)
          def pow(base, exponent = 2):
            return base ** exponent

        Instance example::

          def pow(base, exponent = 2):
            return base ** exponent

          server.sign_named_request(base = int, exponent = 2)(pow)
        """

        def wrap(method: Callable) -> Callable:
            signature = getattr(wrap, "signature", None)
            fn = self._find_method_by_function(method)
            if fn is None:
                self.methods.append(
                    MethodBasedWebServiceAPIServerBase.WebServiceMethod(
                        method,
                        method.__name__,
                        method.__doc__,
                        None,
                        None,
                        False,
                        signature,
                        None,
                    )
                )
            else:
                fn.named_signature = kwargs
            return method

        setattr(wrap, "signature", kwargs)
        return wrap

    def parse_method_call(
        self, request: Request
    ) -> Tuple[str, Optional[list], Optional[dict]]:
        """
        Parses a method call into the method and arguments.

        :param request str: The request, in string form.
        :returns tuple: A three-tuple of (str, list, dict), where the first argument is the method name, and the second the arguments, and the third the named arguments.
        :raises NotImplementedError: The base class will always raise this.
        """
        raise NotImplementedError()

    def format_response(self, result: Any, request: Request, response: Response) -> str:
        """
        Formats a response into something the requester is expecting.

        :param response object: The response from the method call.
        :param request webob.Request: The original request object, in case data in it needs to be referenced.
        :raises NotImplementedError: The base class will always raise this.
        """
        raise NotImplementedError()

    @staticmethod
    def map_typename(_type: Type) -> str:
        """
        Takes a python type and turns it into a string version of it.

        :param _type Type: The type.
        :returns str: The typename of the object.
        :raises TypeError: When no type information is available.
        :raises NotImplementedError: When instantiating the base class.
        """
        raise NotImplementedError()

    def handle(self, request: Request, response: Response) -> str:
        """
        Handles a request by searching for a method to call, calling it, then formatting the response into the response object.

        :param request webob.Request: The request object.
        :param response webob.Response: The response object.
        """
        try:
            method, args, kwargs = self.parse_method_call(request.body)
            if args is None:
                args = []
            if kwargs is None:
                kwargs = {}
            return self.format_response(
                result=self.dispatch(method, *args, **kwargs),
                request=request,
                response=response,
            )
        except (UnsupportedMethodError, BadRequestError) as ex:
            return self.format_exception(
                exception=ex, request=request, response=response
            )
        except Exception as ex:
            logger.error(
                "Received unexpected exception {0} when dispatching a request: {1}".format(
                    type(ex).__name__, str(ex)
                )
            )
            logger.error(format_exc())
            raise ex

    def dispatch(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Dispatches a request by method name.

        :param method_name str: The method to call
        :param args tuple: The argument to pass into the method.
        :raises pibble.api.exceptions.UnsupportedMethodError: when the method is not found.
        """
        fn = self._find_method_by_name(method_name)
        if not fn or not fn.registered:
            raise UnsupportedMethodError("{0} does not exist.".format(method_name))
        return fn(*args, **kwargs)

    class WebServiceMethod:
        """
        A class to hold the method, name, signature, etc.

        Not meant to be instantiated outside of the parent class.
        """

        def __init__(
            self,
            method: Callable,
            name: str,
            docstring: Optional[str] = None,
            signature: Optional[List[List[Type]]] = [],
            response_signature: Optional[Type] = None,
            registered: bool = False,
            named_signature: Optional[Dict[str, Type]] = None,
            response_named_signature: Optional[Dict[str, Type]] = None,
        ) -> None:
            self.method = method
            self.name = name
            self.docstring = docstring
            self.signature = signature
            self.response_signature = response_signature
            self.named_signature = named_signature
            self.response_named_signature = response_named_signature
            self.registered = registered

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            if self.signature:
                types = [type(arg) for arg in args]
                if not any(
                    [signature_part == types for signature_part in self.signature]
                ):
                    raise BadRequestError(
                        "{0} requires arguments of one of the following types: {1}. You sent {2}".format(
                            self.name,
                            ", ".join(
                                [
                                    "({0})".format(
                                        ", ".join(
                                            [
                                                type_part.__name__
                                                for type_part in signature_part
                                            ]
                                        )
                                    )
                                    for signature_part in self.signature
                                ]
                            ),
                            "({0})".format(
                                ", ".join([type(arg).__name__ for arg in args])
                            ),
                        )
                    )
            elif self.named_signature:
                for key in self.named_signature:
                    if type(self.named_signature[key]) is type:
                        if key not in kwargs:
                            raise BadRequestError(
                                "Missing mandatory parameters. Required parameter keys are {0}".format(
                                    ", ".join(
                                        [
                                            key
                                            for key in self.named_signature
                                            if type(self.named_signature[key]) is type
                                        ]
                                    )
                                )
                            )
                        elif type(kwargs[key]) is not self.named_signature[key]:
                            raise BadRequestError(
                                "Parameter {0} is not of type {1} (given type {2})".format(
                                    key,
                                    self.named_signature[key].__name__,
                                    type(kwargs[key]).__name__,
                                )
                            )
            response = self.method(*args, **kwargs)
            if self.response_signature:
                if type(response) is not self.response_signature:
                    raise BadResponseError(
                        "Method {0} returned {1}, but was meant to return {2}. This is a server-side error.".format(
                            self.name,
                            type(response).__name__,
                            self.response_signature.__name__,
                        )
                    )
            elif self.response_named_signature:
                if not isinstance(response, dict):
                    raise BadResponseError(
                        "Method {0} must return a dictionary, but returned {1} instead. This is a server-side error.".format(
                            self.name, type(response).__name__
                        )
                    )
                for key in self.response_named_signature:
                    if type(self.response_named_signature[key]) is type:
                        if key not in response:
                            raise BadResponseError(
                                "Method {0} did not return parameter {1}. This is a server-side error.".format(
                                    self.name, key
                                )
                            )
                        elif (
                            type(response[key])
                            is not self.response_named_signature[key]
                        ):
                            raise BadResponseError(
                                "Method {0} returned parameter {1} of type {2}, but was meant to return type {3}. This is a server-side error.".format(
                                    self.name,
                                    key,
                                    type(response[key]).__name__,
                                    self.response_named_signature[key].__name__,
                                )
                            )
                    elif key not in response:
                        response[key] = self.response_named_signature[key]
            return response

        def __repr__(self) -> str:
            return repr(dict(vars(self)))
