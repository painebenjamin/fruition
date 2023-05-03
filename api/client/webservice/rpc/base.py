from __future__ import annotations

from typing import Callable, Any, Type, Optional, List, Dict

from pibble.util.log import logger
from pibble.util.strings import pretty_print
from pibble.api.exceptions import BadRequestError, UnsupportedMethodError
from pibble.api.client.webservice.base import WebServiceAPIClientBase


class RPCClientBase(WebServiceAPIClientBase):
    """
    A base class for RPC Clients.

    This class does not care about any arguments of its own constructor, it merely passes it to its parent class.
    After parent initialization, it performs its own initialization, generating the system methods, and calling
    the server to ask for its definition.
    """

    methods: List[RPCClientBase.RPCMethod]

    def __init__(self) -> None:
        super(RPCClientBase, self).__init__()
        if not self.configuration.has("client.path"):
            self.configuration["client.path"] = "/RPC2"
        self.methods = [
            RPCClientBase.RPCMethod(self, "system.listMethods", [[list]]),
            RPCClientBase.RPCMethod(self, "system.methodHelp", [[str, str]]),
            RPCClientBase.RPCMethod(self, "system.methodSignature", [[list, str]]),
        ]
        self.introspected = False
        self.introspection_failed = False

    def listMethods(self) -> List[str]:
        """
        Lists the methods in the client.
        """
        return [method.name for method in self.methods]

    def on_configure(self) -> None:
        """
        This fires when a client is configured.
        """
        self.introspect()

    def introspect(self) -> None:
        """
        Attempts to introspect the service.
        """
        self.introspected = True
        try:
            methods = self["system.listMethods"]()
            for method in methods:
                if method not in [known_method.name for known_method in self.methods]:
                    signature_response = self["system.methodSignature"](method)
                    if isinstance(signature_response, list):
                        if signature_response and not isinstance(
                            signature_response[0], list
                        ):
                            # Only one set of signatures responsed
                            signature = [
                                [
                                    self.map_typename(typename)
                                    for typename in signature_response
                                ]
                            ]
                        else:
                            signature = [
                                [
                                    self.map_typename(typename)
                                    for typename in signature_part
                                ]
                                for signature_part in signature_response
                            ]
                        self.methods.append(
                            RPCClientBase.RPCMethod(self, method, signature)
                        )
                    else:
                        self.methods.append(
                            RPCClientBase.RPCMethod(
                                self, method, None, signature_response
                            )
                        )
        except UnsupportedMethodError:
            # Server does not support introspection.
            self.introspection_failed = True

    def _find_method_by_name(self, method_name: str) -> Callable:
        """
        Finds a method by its name using list comprehension.

        :raises pibble.api.exceptions.UnsupportedMethodError: When the method is not defined.
        """
        if not self.introspected:
            self.introspect()
        method = [method for method in self.methods if method.name == method_name]
        if not method:
            if self.introspection_failed:
                # Server may not support introspection, try this method anyway.
                new_method = RPCClientBase.RPCMethod(self, method_name, None)
                self.methods.append(new_method)
                return new_method
            else:
                raise UnsupportedMethodError(
                    "Method '{0}' is not defined.".format(method_name)
                )
        return method[0]

    def format_request(self, method_name: str, *args: Any, **kwargs: Any) -> str:
        """
        Takes a request to perform a method, and turns it into a string-like object to send over the transport.

        :param method_name str: The method to call.
        :param args tuple: The arguments to pass in.
        :param kwargs dict: The named arguments to pass in.
        :returns str: The stringified response to send.
        :raises NotImplementedError: When instantiating the base class.
        """
        raise NotImplementedError()

    def format_response(self, response: Any) -> Any:
        """
        Takes a response from a method, and turns it into python-understood types.

        :param response str: The response from the method.
        :returns tuple: The object(s) from the response.
        :raises NotImplementedError: When instantiating the base class.
        """
        raise NotImplementedError()

    @staticmethod
    def map_typename(typename: str) -> Type:
        """
        Takes a string typename ("string", "float", etc.) and turns it into a python type.

        :param typename str: The typname.
        :returns Type: The type of the object.
        :raises NotImplementedError: When instantiating the base class.
        :raises TypeError: When no type information is available.
        """
        raise NotImplementedError()

    def __getattr__(self, method_name: str) -> Callable:
        """
        This allows for client.methodName calls. If a method name is dot-separated, you MUST use client["methodName"].
        """
        return self._find_method_by_name(method_name)

    def __getitem__(self, method_name: str) -> Callable:
        """
        This allows for client["methodName"] calls.
        """
        return self._find_method_by_name(method_name)

    class RPCMethod:
        """
        This class will hold the method name, as well as any signature it has supplied.

        If the signature was returned successfully, both the arguments and the response will be checked.

        The function can be called like any other function, thanks to the `__call__` method.

        :param name str: The name of the function. Can be dot-separated.
        :param arguments list: A list of argument types. Can be None if no signature is supplied. This is a list of lists, where each component list is of the form [return_type, type, type, ...].
        """

        def __init__(
            self,
            client: RPCClientBase,
            name: str,
            arguments: Optional[list] = None,
            named_arguments: Optional[Dict[str, Any]] = None,
        ):
            self.client = client
            self.name = name
            self.arguments = arguments
            self.named_arguments = named_arguments

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            if self.arguments is not None:
                argument_types = [type(arg) for arg in args]
                if not any(
                    [
                        argument_type[1:] == argument_types
                        for argument_type in self.arguments
                    ]
                ):
                    raise BadRequestError(
                        "Bad argument types. You passed ({0}), your request must be one of {1}".format(
                            pretty_print(*[t.__name__ for t in argument_types]),
                            " or ".join(
                                [
                                    "({0})".format(
                                        pretty_print(
                                            *[t.__name__ for t in argument_type[1:]]
                                        )
                                    )
                                    for argument_type in self.arguments
                                ]
                            ),
                        )
                    )
            elif self.named_arguments is not None:
                for key in self.named_arguments:
                    if isinstance(self.named_arguments[key], str):
                        try:
                            self.named_arguments[key] = self.client.map_typename(
                                self.named_arguments[key]
                            )
                        except TypeError as ex:
                            pass

                if any(
                    [
                        key not in kwargs
                        and isinstance(self.named_arguments[key], type)
                        for key in self.named_arguments
                    ]
                ):
                    raise BadRequestError(
                        "Missing named request parameters. Your request must include ({0})".format(
                            ", ".join(
                                [
                                    key
                                    for key in self.named_arguments
                                    if isinstance(self.named_arguments[key], type)
                                ]
                            )
                        )
                    )
                else:
                    for key in self.named_arguments:
                        if isinstance(
                            self.named_arguments[key], type
                        ) and not isinstance(kwargs[key], self.named_arguments[key]):
                            raise BadRequestError(
                                "Bad argument type for named parameter {0}. You passed {1}, your request must be {2}.".format(
                                    key,
                                    type(kwargs[key]).__name__,
                                    self.named_arguments[key].__name__,
                                )
                            )
            response = self.client.format_response(
                self.client.post(
                    data=self.client.format_request(self.name, *args, **kwargs)
                ).text
            )
            response_type = type(response)
            if self.arguments is not None:
                if not any(
                    [
                        response_type == argument_type[0]
                        for argument_type in self.arguments
                    ]
                ):
                    logger.warning("Bad response: {0}".format(response))
                    raise BadRequestError(
                        "Bad response type. The server responded with {0}, but it must be one of {1}".format(
                            response_type.__name__,
                            " or ".join(
                                [
                                    "({0})".format(argument_type[0].__name__)
                                    for argument_type in self.arguments
                                ]
                            ),
                        )
                    )
            if isinstance(response, list) and len(response) == 1:
                return response[0]
            return response
