from __future__ import annotations

import io
import logging
import traceback

from typing import Optional, Callable, Any, List
from webob import Request, Response

from pibble.util.helpers import CompressedIterator
from pibble.util.strings import truncate
from pibble.util.log import logger
from pibble.api.exceptions import ConfigurationError
from pibble.api.server.base import APIServerBase
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.server.webservice.handler import (
    WebServiceAPIHandler,
    WebServiceAPIHandlerRegistry,
)
from pibble.api.server.webservice.template.loader import TemplateLoader


class TemplateHandler(WebServiceAPIHandler):
    """
    A small extension to the base handler to allow for template responses.
    """

    def __init__(
        self,
        function: Callable,
        template: Optional[str] = None,
        errors: Optional[List[int]] = [],
        **kwargs: Any,
    ):
        super(TemplateHandler, self).__init__(function, **kwargs)
        self.template = template
        self.errors = errors

    def __call__(
        self,
        server: APIServerBase,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.template is not None and isinstance(server, TemplateServer):
            response.content_type = (
                "text/html"  # Push default now, this could be changed in handler
            )
            server.prepare_context_all(request, response)
            try:
                context = self.function(server, request, response, *args, **kwargs)
            except:
                logger.error(
                    "Template handler function raised exception, abandoning template render."
                )
                raise
            if not isinstance(context, dict):
                raise ConfigurationError(
                    "Template handler did not return a context dictionary."
                )
            try:
                logger.debug(f"Rendering template {self.template}")
                rendered = server.templates.render(
                    self.template, **{**getattr(request, "context", {}), **context}
                )
                if not rendered:
                    logger.warn("Template rendered empty.")
                return rendered
            except:
                logger.critical("Exception during template rendering.")
                raise
        else:
            return super(TemplateHandler, self).__call__(
                server, request, response, *args, **kwargs
            )

    def __repr__(self) -> str:
        return "{0} (template: {1}, errors: {2})".format(
            super(TemplateHandler, self).__repr__(), self.template, self.errors
        )


class TemplateServerHandlerRegistry(WebServiceAPIHandlerRegistry):
    def template(self, filename: str) -> Callable[[Callable], Callable]:
        """
        Registers a template handler.

        - Template handlers should respond with a dictionary containing context for said template.
        - Template hanlders will look for <filename> in the handler registry template directories.
          * Directories are traversed in the order they were passed to the registry.
        - When a template is not found, it is considered a configuration error.
        - Templates use Jinja2 to render.
        - Templates are **always** given a variable of `csrf_token`. They can be ignored if so desired.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, template=filename)
            return fn

        return wrap

    def errors(self, *codes: int) -> Callable[[Callable], Callable]:
        """
        Marks a handler as an error handler.

        When a response has an error code, the TemplateServer can intercept and respond with an
        error handler. This is generally also a template handler, but needn't be.

        :param codes tuple: Any number of error codes to handle.
        """

        def wrap(fn: Callable) -> Callable:
            self.create_or_modify_handler(fn, errors=[int(code) for code in codes])
            return fn

        return wrap

    def create_handler(self, fn: Callable, **kwargs: Any) -> TemplateHandler:
        """
        Creates a handler.

        Overridden to use the TemplateHandler class.
        """
        handler = TemplateHandler(fn, **kwargs)
        self.handlers.append(handler)
        return handler


class TemplateServer(WebServiceAPIServerBase):
    """
    This is a small extension on the base server to add error handlers and template loaders.
    """

    class_handlers: List[WebServiceAPIHandlerRegistry]

    def on_configure(self) -> None:
        """
        Create the template loader.

        This does not require any actual configuration, but see :class:pibble.api.server.webservice.html.server.TemplateServerTemplateLoader for optional keys.
        """
        if not hasattr(self, "templates"):
            logger.debug("Creating template loader.")
            self.templates = TemplateLoader(self.configuration, server=self)

    def prepare_context_all(self, request: Request, response: Response) -> None:
        """
        Runs all "prepareContext" functions.
        """

        handler = getattr(request, "handler", None)
        if not hasattr(request, "context"):
            setattr(request, "context", {})
        for cls in reversed(type(self).mro()):
            if hasattr(cls, "prepare_context") and "prepare_context" in cls.__dict__:
                if handler is None or (
                    handler is not None and cls not in handler.bypass
                ):
                    logger.debug(
                        "Running context preparation for class {0}".format(cls.__name__)
                    )
                    try:
                        request.context = {
                            **request.context,
                            **cls.prepare_context(self, request, response),
                        }
                    except Exception as ex:
                        logger.error(
                            "Could not execute context preparation for class '{0}' - {1}: {2}".format(
                                cls.__name__, type(ex).__name__, ex
                            )
                        )
                        pass

    def prepare_context(self, request: Request, response: Response) -> dict:
        """
        The base "prepare_context" function passes through configuration.
        """
        return {"configuration": self.configuration}

    def prepare(
        self, request: Optional[Request] = None, response: Optional[Response] = None
    ) -> None:
        """
        We add a `prepare()` method to the Template server to invoke error handlers when possible.
        """
        if response is not None and response.status_code >= 400:
            logger.debug(
                "Response status code is {0}, looking for error handlers.".format(
                    response.status_code
                )
            )
            for registry in self.class_handlers:
                for handler in registry.handlers:
                    if response.status_code in getattr(handler, "errors", []):
                        logger.debug("Found error handler {0}".format(handler))
                        try:
                            result = handler(self, request, response)
                            accepted_encodings = ""
                            if request is not None:
                                accepted_encodings = request.headers.get(
                                    "Accept-Encoding", ""
                                )
                            if (
                                handler.compress_response
                                and "gzip" in accepted_encodings
                                and result
                            ):
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "Error handler compressing result {0}".format(
                                            truncate(str(result))
                                        )
                                    )
                                if isinstance(result, str):
                                    result = result.encode("utf-8")
                                response.app_iter = CompressedIterator(
                                    io.BytesIO(result)
                                )
                                response.headers["Content-Encoding"] = "gzip"
                            elif isinstance(result, str):
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "Error handler returning result {0}".format(
                                            truncate(str(result))
                                        )
                                    )
                                response.text = result
                        except Exception as ex:
                            logger.error(
                                "Error handler raised exception {0}({1})".format(
                                    type(ex).__name__, str(ex)
                                )
                            )
                            logger.debug(traceback.format_exc())
                            response.status_code = 500
                            response.text = self.format_exception(ex, request, response)
                        break
