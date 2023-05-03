from typing import Any, Optional, Union, Type
from urllib.parse import urlencode

from pibble.util.log import logger
from pibble.api.exceptions import ConfigurationError
from pibble.api.helpers.wrappers import RequestWrapper, ResponseWrapper, SessionWrapper
from pibble.api.client.wrapper import APIClientWrapperBase
from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.api.client.webservice.jsonapi import JSONWebServiceAPIClient

from requests import Request, Response

__all__ = [
    "WebServiceAPIClientWrapper",
    "WebServiceAPILambdaTestClientWrapper",
    "WebServiceAPILambdaClientWrapper",
]


class WebServiceAPIClientSessionWrapper(SessionWrapper):
    """
    This implementation of the SessionWrapper simply issues a `handle_request` method
    call to the implementing server.
    """

    def send(self, request: RequestWrapper, **kwargs: Any) -> ResponseWrapper:
        """
        Send the request directly to the servers' `handle_response` method.
        """
        response = ResponseWrapper()
        if not hasattr(request.server, "handle_request"):
            raise ConfigurationError(
                "Configured server does not extend WebServiceAPIServerBase, you cannot use this client wrapper to handle requests."
            )
        logger.debug(
            "Client wrapper issuing request {0} from client {1} to server {2}".format(
                request, request.client, request.server
            )
        )
        request.server.handle_request(request, response)  # type: ignore
        logger.debug("Client wrapper received response {0}".format(response))
        return response


class WebServiceAPIClientWrapper(WebServiceAPIClientBase, APIClientWrapperBase):
    """
    This allows for easy abstraction of HTTP methods using wrappers.
    """

    session_class: Type[SessionWrapper] = WebServiceAPIClientSessionWrapper
    request_class = RequestWrapper
    response_class = ResponseWrapper

    def prepare(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
    ) -> None:
        """
        During the prepare() step for a client, we set the wrappers' client and server variables.
        """
        if isinstance(request, RequestWrapper):
            request.client = self
            request.server = self.server
        if isinstance(response, ResponseWrapper):
            response.client = self
            response.server = self.server


class WebServiceAPILambdaTestClientSessionWrapper(SessionWrapper):
    """
    This session uses the `handle_lambda_request` method of the server, instead of `handle_request`.
    """

    def send(self, request: RequestWrapper, **kwargs: Any) -> ResponseWrapper:
        """
        Send the request directly to the servers' `lambda_handler` method, converting the
        request to fit that format. Really only useful for testing.
        """
        response = ResponseWrapper()
        if request.server is None:
            raise ConfigurationError("Server not set.")
        if not hasattr(request.server, "handle_lambda_request"):
            raise ConfigurationError(
                "Configured server does not extend LambdaWebServiceAPI, you cannot use this client wrapper to handle requests."
            )
        logger.debug(
            "Client wrapper issuing request {0} from client {1} to server {2} via lambda compatibility function. Headers: {3}".format(
                request, request.client, request.server, request.headers
            )
        )
        event = {
            "version": "2.0",
            "rawPath": request.path,
            "rawQueryString": "" if not request.params else urlencode(request.params),
            "headers": request.headers,
            "body": request.text,
            "requestContext": {
                "http": {
                    "method": request.method,
                    "path": request.path,
                    "sourceIp": "127.0.0.1",
                    "userAgent": "pibble/WebServiceAPILambdaClientSessionWraper",
                }
            },
        }
        lambda_response = request.server.handle_lambda_request(event)  # type: ignore
        response.status_code = lambda_response["statusCode"]
        response.body = lambda_response["body"]
        for header in lambda_response["headers"]:
            response.headers[header] = lambda_response["headers"][header]
        logger.debug("Client wrapper received response {0}".format(response))
        return response


class WebServiceAPILambdaTestClientWrapper(WebServiceAPIClientWrapper):
    session_class = WebServiceAPILambdaTestClientSessionWrapper


class WebServiceAPILambdaClientSessionWrapper(SessionWrapper):
    """
    This session actually issues a lambda request to a docker container running a lambda app.
    """

    def on_configure(self) -> None:
        """
        On configure, build a client to the docker image.
        """

    def send(self, request: RequestWrapper, **kwargs: Any) -> ResponseWrapper:
        """
        Build a request to the lambda client.
        Send the request directly to the servers' `lambda_handler` method, converting the
        request to fit that format. Really only useful for testing.
        """
        if request.client is None:
            raise ConfigurationError("Client not initialized.")

        response = ResponseWrapper()
        logger.debug(
            "Client wrapper issuing request {0} from client {1} via lambda client. Headers: {2}".format(
                request, request.client, request.headers
            )
        )
        lambda_client = JSONWebServiceAPIClient()
        lambda_client.configure(
            client={
                "host": request.client.configuration.get("client.host", "127.0.0.1"),
                "port": request.client.configuration.get("client.port", "9000"),
                "path": request.client.configuration.get(
                    "client.invoke", "/2015-03-31/functions/function/invocations"
                ),
                "secure": request.client.configuration.get("client.secure", False),
            }
        )
        event = {
            "version": "2.0",
            "rawQueryString": "" if not request.params else urlencode(request.params),
            "headers": request.headers,
            "body": request.text,
            "requestContext": {
                "http": {
                    "method": request.method,
                    "path": request.path,
                    "sourceIp": "127.0.0.1",
                    "userAgent": "pibble/WebServiceAPILambdaClientSessionWraper",
                }
            },
        }

        lambda_response = lambda_client.post(data=event).json()
        response.status_code = lambda_response["statusCode"]
        response.body = lambda_response["body"]
        for header in lambda_response["headers"]:
            response.headers[header] = lambda_response["headers"][header]
        logger.debug("Client wrapper received response {0}".format(response))
        return response


class WebServiceAPILambdaClientWrapper(WebServiceAPIClientWrapper):
    request_class = RequestWrapper
    response_class = ResponseWrapper
    session_class = WebServiceAPILambdaClientSessionWrapper
