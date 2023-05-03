from __future__ import annotations

import lxml.etree as ET

from typing import Callable, Any, Optional, Union, Dict, List, cast
from functools import partial
from requests import Request, Response

from zeep import Client
from zeep.transports import Transport
from zeep.wsdl.definitions import Operation, AbstractMessage

from pibble.api.helpers.wrappers import RequestWrapper, ResponseWrapper
from pibble.api.client.webservice.base import WebServiceAPIClientBase
from pibble.util.helpers import url_join


class SOAPError(Exception):
    def __init__(self, response: Union[Response, ResponseWrapper]) -> None:
        self.response = response
        super(Exception, self).__init__(self.response.text)


class SOAPClient(WebServiceAPIClientBase):
    """
    A SOAP client using the Zeep library.

    We define a `zeep.transports.Transport` as the client itself, so we can
    break in using middleware if we so desire.

    :param wsdl str: The WSDL (web service description language) documentation as a URI.
    """

    soap: Client

    def __init__(self) -> None:
        super(SOAPClient, self).__init__()

    def on_configure(self) -> None:
        host = self.configuration["client.host"]
        scheme = self.configuration.get("client.scheme", "http")
        port = int(
            self.configuration.get("client.port", 80 if scheme == "http" else 443)
        )
        path = self.configuration.get("client.path", "/")
        url = url_join("{0}://{1}:{2}/".format(scheme, host, port), path)
        self.soap = Client(url, transport=SOAPClient.ZeepTransport(self))  # type: ignore

    def _get_operation(self, method: str) -> Operation:
        """
        Gets an operation from the service.

        This returns the WSDL node that zeep retrieves.

        :param method str: The method name.
        :raises KeyError: When the operation is undefined.
        """
        for service in self.soap.wsdl.services.values():
            for port in service.ports.values():
                for operation in port.binding._operations.values():
                    if operation.name == method:
                        return cast(Operation, operation)
        raise KeyError("Unknown or disallowed method {0}".format(method))

    def listMethods(self) -> List[str]:
        """
        Lists methods in the service.
        """
        return [
            method
            for method in dir(self.soap.service)
            if not method.startswith("_")
            and callable(getattr(self.soap.service, method))
        ]

    def methodHelp(self, method: str) -> str:
        """
        Returns a string which shows input/output for a particular method.

        :param method str: The method name.
        :raises KeyError: When the operation is undefined.
        """

        def elementHelp(name: str, element: ET._Element) -> str:
            if hasattr(element.type, "elements"):
                return "{0} - {1}\n{2}".format(
                    name, element.type.name, elementsHelp(element.type.elements)
                )
            else:
                return "{0} - {1}".format(name, element.type)

        def elementsHelp(elements: List[ET._Element], indent: int = 2) -> str:
            return "\n".join(
                [
                    "\n".join(
                        [
                            "{0}{1}".format(" " * indent, line)
                            for line in elementHelp(name, element).splitlines()
                        ]
                    )
                    for name, element in elements
                ]
            )

        operation = self._get_operation(method)

        return "{0}\nInput\n{1}\nOutput\n{2}".format(
            operation.name,
            elementsHelp(operation.input.body.type.elements),
            elementsHelp(operation.output.body.type.elements),
        )

    def _call_function(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Intercepts function calls to be able to convert pre-made types into dictionaries.
        """
        result = getattr(self.soap.service, method_name)(*args, **kwargs)
        if type(result).__module__ != "builtins":
            return dict(result.__json__())
        return result

    def __getattr__(self, method_name: str) -> Callable:
        """
        Overrides client.methodName calls. Exposes methods.
        :param method_name str: The method to call.
        :raises KeyError: When the method does not exist.
        """
        try:
            return self[method_name]
        except KeyError:
            raise AttributeError(method_name)

    def __getitem__(self, method_name: str) -> Callable:
        """
        Overrides client[method_name] calls. Effectively exposes methods.

        :param method_name str: The method to call.
        :raises KeyError: When the method does not exist.
        """
        if method_name == "soap":
            return None  # type: ignore
        if method_name in self.listMethods():
            return partial(self._call_function, method_name)
        raise KeyError("Unknown or disallowed method '{0}'.".format(method_name))

    def parse(
        self,
        request: Optional[Union[Request, RequestWrapper]] = None,
        response: Optional[Union[Response, ResponseWrapper]] = None,
    ) -> None:
        """
        Parses the response from requests.

        If there is an exception, this will raise a SOAPError which will be caught by
        the transport layer, then parsed by zeep.
        """
        if response and not 200 <= response.status_code < 300:
            raise SOAPError(response)

    class ZeepTransport(Transport):
        """
        A small extension of the zeep transport which includes middleware processing.
        """

        def __init__(self, client: SOAPClient) -> None:
            super(SOAPClient.ZeepTransport, self).__init__()  # type: ignore
            self.client = client

        def get(
            self, address: str, params: Dict[str, Any], headers: Dict[str, Any]
        ) -> Union[Response, ResponseWrapper]:
            try:
                return self.client.get(address, parameters=params, headers=headers)
            except SOAPError as ex:
                return ex.response

        def post(
            self, address: str, message: AbstractMessage, headers: Dict[str, Any]
        ) -> Union[Response, ResponseWrapper]:
            try:
                return self.client.post(address, data=message, headers=headers)
            except SOAPError as ex:
                return ex.response

        def _load_remote_data(self, url: str) -> bytes:
            return self.get(url, {}, {}).content
