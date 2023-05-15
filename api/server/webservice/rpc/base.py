from webob import Request, Response

from pibble.api.server.webservice.base import MethodBasedWebServiceAPIServerBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from pibble.api.exceptions import (
    UnsupportedMethodError,
    ConfigurationError,
)
from typing import Type, Optional, Union, List, Dict


class RPCServerBase(MethodBasedWebServiceAPIServerBase):
    """
    A base server for RPC classes.

    This will handle function registration and dispatching. Inherited classes are responsible for parsing and formatting requests and responses.
    """

    handlers = WebServiceAPIHandlerRegistry()

    def __init__(self) -> None:
        super(RPCServerBase, self).__init__()
        self.register_introspection_functions()

    def register_introspection_functions(self) -> None:
        """
        Registers introspection functions for an RPC server.

        This grants the following methods:
          1. system.listMethods
          2. system.methodSignature
          3. system.methodHelp

        See the source for each methods return and help (or, deploy a server and ask it yourself.)
        """

        fn = self.register("system.listMethods")(self.list_methods)
        self.sign_response(list)(fn)

        fn2 = self.register("system.methodSignature")(self.method_signature)
        self.sign_request(str)(fn2)
        self.sign_response(list)(fn2)

        fn3 = self.register("system.methodHelp")(self.method_help)
        self.sign_request(str)(fn3)
        self.sign_response(str)(fn3)

    def list_methods(self) -> List[str]:
        """
        Returns a list of all methods.

        :returns list: A list of function names.
        """
        return [method.name for method in self.methods if method.name]

    def method_signature(
        self, fn_name: str
    ) -> Optional[Union[List[List[Type]], List[Dict[str, Type]]]]:
        """
        Returns the signature of a method.

        Returns None if no signature is known or it takes no parameters.

        :param fn_name str: The function to return.
        :returns list: A list of lists of types.
        :raises pibble.api.exceptions.UnsupportedMethodError: when the method is not found.
        """
        fn = self._find_method_by_name(fn_name)
        if fn is None:
            raise UnsupportedMethodError("{0} does not exist.".format(fn_name))
        if fn.named_signature:
            return [fn.named_signature]
        elif not fn.signature:
            raise ConfigurationError(
                "Method {0} is missing a signature.".format(fn_name)
            )
        signatures: List[List[Type]] = []
        for signature in fn.signature:
            if fn.response_signature is not None:
                signatures.append([fn.response_signature] + signature)
            else:
                signatures.append(signature)
        if not fn.signature and fn.response_signature:
            signatures = [[fn.response_signature]]
        if not signatures:
            return None
        return signatures

    def method_help(self, fn_name: str) -> str:
        """
        Returns the docstring of a method.

        :param fn_name str: The function to retrieve the docstring for.
        :returns str: The docstring of the method.
        :raises pibble.api.exceptions.UnsupportedMethodError: when the method is not found.
        """
        fn = self._find_method_by_name(fn_name)
        if fn is None:
            raise UnsupportedMethodError("{0} does not exist.".format(fn_name))
        if not fn.docstring:
            return ""
        return "\n".join(
            [line.strip() for line in fn.docstring.splitlines() if line.strip()]
        )

    @handlers.path("/RPC2")
    @handlers.methods("POST")
    def rpc(self, request: Request, response: Response) -> str:
        """
        Handles a request by searching for a method to call, calling it, then formatting the response into the response object.

        :param request webob.Request: The request object.
        :param response webob.Response: The response object.
        """
        return self.handle(request, response)
