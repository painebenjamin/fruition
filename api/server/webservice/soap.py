import datetime

from lxml import etree as ET
from lxml.builder import ElementMaker

from typing import Type, Optional, Any, Iterator, Tuple, List, Dict, cast

from webob import Request, Response

from pibble.api.server.webservice.base import MethodBasedWebServiceAPIServerBase
from pibble.api.server.webservice.handler import WebServiceAPIHandlerRegistry
from pibble.api.exceptions import (
    UnsupportedMethodError,
    BadRequestError,
    ConfigurationError,
    NotFoundError,
)
from pibble.util.strings import decode, encode, Serializer
from pibble.util.log import logger


class MultiNamespaceElementBuilder:
    """
    A helper class for generating XML elements in multiple namespaces at once.

    :param nsmap dict: A dictionary of shortname -> schema.
    """

    def __init__(self, **nsmap: str):
        self.namespaces = dict(nsmap)

    def __getattr__(self, ns: str) -> ElementMaker:
        if ns not in self.namespaces:
            raise KeyError(f"Unknown namespace {ns}")
        return ElementMaker(namespace=self.namespaces[ns], nsmap=self.namespaces)


class SOAPServer(MethodBasedWebServiceAPIServerBase):
    """
    A SOAP server class that operates similarly to the RPC classes.

    Note this is far from a complete implementation, it only manages unary requests/responses,
    and is limited in its nesting ability of types.

    When deployed, it will register three endpoints;
      - http(s)://<server.hostname>:<server.port>/<server.name>.wsdl
      - http(s)://<server.hostname>:<server.port>/<server.name>.xsd
      - http(s)://<server.hostname>:<server.port>/services/<server.name>

    Note that the socket will still listen on <server.host>.

    Optional Configuration:
      - `server.hostname`: The hostname of the server. Defaults to loopback - '127.0.0.1'.
      - `server.name`: The name of the service. Defaults to "SOAPServer".
    """

    handlers = WebServiceAPIHandlerRegistry()

    @staticmethod
    def get_type(obj: Type) -> str:
        """
        Takes a python type and turns it into the xsd equivalent.
        """
        return {
            int: "xsd:int",
            float: "xsd:decimal",
            datetime.datetime: "xsd:datetime",
            bool: "xsd:boolean",
            bytes: "xsd:base64Binary",
            str: "xsd:string",
        }[obj]

    def _generate_xsd(self) -> ET._Element:
        """
        This generates the XSD document detailing request/response
        types for registered methods.
        """

        ssl = self.configuration.get("server.secure", False)
        hostname = self.configuration.get("server.hostname", "127.0.0.1")
        name = self.configuration.get("server.name", "SOAPServer")
        path = "{protocol}://{hostname}:{port}{path}".format(
            protocol="https" if ssl else "http",
            hostname=hostname,
            path=self.configuration.get("server.path", "/"),
            port=self.configuration["server.port"],
        )

        xmlnsxsd = "{0}{1}.xsd".format(path, name)

        nsmap = {"xsd": "http://www.w3.org/2001/XMLSchema"}

        E = MultiNamespaceElementBuilder(**nsmap)

        def _get_types() -> Iterator[ET._Element]:
            def _list_node(name: str, lst: List[Type]) -> Iterator[ET._Element]:
                for node in _dict_node(
                    name,
                    dict(zip(["listIndex{0}".format(i) for i in range(len(lst))], lst)),
                ):
                    yield node

            def _dict_node(name: str, dct: Dict[str, Type]) -> Iterator[ET._Element]:
                if len(dct.keys()) == 1:
                    key = list(dct.keys())[0]
                    yield E.xsd.element(
                        E.xsd.complexType(
                            E.xsd.all(
                                E.xsd.element(name=key, type=self.get_type(dct[key]))
                            ),
                            name=name,
                        ),
                        name=name,
                    )
                else:
                    yield E.xsd.element(
                        E.xsd.complexType(
                            E.xsd.sequence(
                                *[
                                    E.xsd.element(
                                        name=key, type=self.get_type(dct[key])
                                    )
                                    for key in dct
                                ]
                            ),
                            name=name,
                        ),
                        name=name,
                    )

            for method in self.methods:
                if (not method.signature and not method.named_signature) or (
                    not method.response_signature
                    and not method.response_named_signature
                ):
                    raise ConfigurationError(
                        "Cannot have non-signed methods when using a SOAP server."
                    )
                if method.signature:
                    for node in _list_node(
                        method.name + "Request", method.signature[0]
                    ):
                        yield node
                elif method.named_signature:
                    for node in _dict_node(
                        method.name + "Request", method.named_signature
                    ):
                        yield node
                if method.response_signature:
                    for node in _list_node(
                        method.name + "Response", [method.response_signature]
                    ):
                        yield node
                elif method.response_named_signature:
                    for node in _dict_node(
                        method.name + "Response", method.response_named_signature
                    ):
                        yield node

        return E.xsd.schema(
            *[node for node in _get_types()],
            **{
                "attributeFormDefault": "qualified",
                "elementFormDefault": "qualified",
                "targetNamespace": xmlnsxsd,
            },
        )

    def _generate_wsdl(self) -> ET._Element:
        """
        This generates the WSDL document describing all registered methods.
        """

        ssl = self.configuration.get("server.secure", False)
        hostname = self.configuration.get("server.hostname", "127.0.0.1")
        name = self.configuration.get("server.name", "SOAPServer")
        path = "{protocol}://{hostname}:{port}{path}".format(
            protocol="https" if ssl else "http",
            hostname=hostname,
            path=self.configuration.get("server.path", "/"),
            port=self.configuration["server.port"],
        )

        xmlns = "{0}{1}.wsdl".format(path, name)
        xmlnsxsd = "{0}{1}.xsd".format(path, name)
        http_tp = "http://schemas.xmlsoap.org/soap/http"

        nsmap = {
            "wsdl": "http://schemas.xmlsoap.org/wsdl/",
            "soap": "http://schemas.xmlsoap.org/wsdl/soap/",
            "soap12": "http://schemas.xmlsoap.org/wsdl/soap12/",
            "mime": "http://schemas.xmlsoap.org/wsdl/mime/",
            "xsd": "http://www.w3.org/2001/XMLSchema",
            "tns": xmlns,
            "xsd1": xmlnsxsd,
        }

        E = MultiNamespaceElementBuilder(**nsmap)

        def _get_messages() -> ET._Element:
            for method in self.methods:
                for typename in ["Request", "Response"]:
                    yield E.wsdl.message(
                        E.wsdl.part(
                            name="body",
                            element="xsd1:{0}{1}".format(method.name, typename),
                        ),
                        name="{0}{1}".format(method.name, typename),
                    )

        return E.wsdl.definitions(
            E.wsdl.documentation(
                self.configuration.get(
                    "server.documentation", "WSDL File for {0}Service".format(name)
                )
            ),
            E.wsdl.types(self._generate_xsd()),
            *[message for message in _get_messages()]
            + [
                E.wsdl.portType(
                    *[
                        E.wsdl.operation(
                            E.wsdl.input(message="tns:{0}Request".format(method.name)),
                            E.wsdl.output(
                                message="tns:{0}Response".format(method.name)
                            ),
                            name=method.name,
                        )
                        for method in self.methods
                    ],
                    **{"name": "{0}PortType".format(name)},
                ),
                E.wsdl.binding(
                    E.soap.binding(transport=http_tp, style="document"),
                    *[
                        E.wsdl.operation(
                            E.soap.operation(
                                soapAction="urn:{0}".format(method.name),
                                style="document",
                            ),
                            E.wsdl.input(E.soap.body(use="literal", namespace=xmlns)),
                            E.wsdl.output(E.soap.body(use="literal", namespace=xmlns)),
                            name=method.name,
                        )
                        for method in self.methods
                    ],
                    **{
                        "name": "{0}Soap11Binding".format(name),
                        "type": "tns:{0}PortType".format(name),
                    },
                ),
                E.wsdl.binding(
                    E.soap12.binding(transport=http_tp, style="document"),
                    *[
                        E.wsdl.operation(
                            E.soap12.operation(
                                soapAction="urn:{0}".format(method.name),
                                style="document",
                            ),
                            E.wsdl.input(E.soap12.body(use="literal")),
                            E.wsdl.output(E.soap12.body(use="literal")),
                            name=method.name,
                        )
                        for method in self.methods
                    ],
                    **{
                        "name": "{0}Soap12Binding".format(name),
                        "type": "tns:{0}PortType".format(name),
                    },
                ),
                E.wsdl.service(
                    E.wsdl.port(
                        E.soap.address(
                            location="{0}services/{1}Soap11Endpoint".format(path, name)
                        ),
                        binding="tns:{0}Soap11Binding".format(name),
                        name="{0}Soap11Port".format(name),
                    ),
                    E.wsdl.port(
                        E.soap12.address(
                            location="{0}services/{1}Soap12Endpoint".format(path, name)
                        ),
                        binding="tns:{0}Soap12Binding".format(name),
                        name="{0}Soap12Port".format(name),
                    ),
                    name="{0}Service".format(name),
                ),
            ],
            **{"targetNamespace": xmlns},
        )

    def parse_method_call(
        self, request: Request
    ) -> Tuple[str, Optional[list], Optional[dict]]:
        """
        Takes a request and parses out the SOAP envelope to obtain the
        method, arguments, and keyword arguments.
        """
        try:
            envelope = ET.fromstring(encode(request.text))
        except ET.XMLSyntaxError:
            logger.error(f"Couldn't parse SOAP envelope {request.text}")
            raise

        body = envelope.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")

        method_node = body[0]
        method_request = method_node.tag.split("}")[1]
        method = method_request[: -1 * len("Request")]

        argsdict = {}
        kwargs = {}
        for child in method_node:
            if child.tag.split("}")[1].startswith("listIndex"):
                index = int(child.tag.split("}")[1][len("listIndex") :])
                argsdict[index] = child.text
            else:
                kwargs[child.tag.split("}")[1]] = child.text
        args = list(argsdict.values())
        fn = self._find_method_by_name(method)
        if not fn or not fn.registered:
            raise UnsupportedMethodError("{0} does not exist.".format(method))

        if fn.signature:
            for i, arg in enumerate(args):
                if (
                    type(fn.signature[0][i]) is type and fn.signature[0][i] is not str
                ) or not isinstance(fn.signature[0][i], str):
                    args[i] = Serializer.deserialize(arg)
        elif fn.named_signature:
            for key in kwargs:
                if key not in fn.named_signature:
                    raise BadRequestError(
                        "Method {0} does not understand keyword argument {1}.".format(
                            method, key
                        )
                    )
                if (
                    type(fn.named_signature[key]) is type
                    and fn.named_signature[key] is not str
                ) or not isinstance(fn.named_signature[key], str):
                    kwargs[key] = Serializer.deserialize(kwargs[key])

        return method, args, kwargs

    def format_response(self, result: Any, request: Request, response: Response) -> str:
        """
        Takes a result and formats it in the appropriate XSD object
        as generated during initial request.
        """
        method = request.soap_method
        fn = self._find_method_by_name(method)
        if not fn or not fn.registered:
            raise UnsupportedMethodError("{0} does not exist.".format(method))
        ssl = self.configuration.get("server.secure", False)
        name = self.configuration.get("server.name", "SOAPServer")
        hostname = self.configuration.get("server.hostname", "127.0.0.1")
        path = "{protocol}://{hostname}:{port}{path}".format(
            protocol="https" if ssl else "http",
            hostname=hostname,
            path=self.configuration.get("server.path", "/"),
            port=self.configuration["server.port"],
        )

        xmlns = "{0}{1}.wsdl".format(path, name)
        xmlnsxsd = "{0}{1}.xsd".format(path, name)

        nsmap = {
            "soapenv": "http://schemas.xmlsoap.org/soap/envelope/",
            "tns": xmlns,
            "xsd1": xmlnsxsd,
        }

        E = MultiNamespaceElementBuilder(**nsmap)

        def _get_node(method: str, result: Any) -> ET._Element:
            if fn.response_signature:  # type: ignore
                if fn.response_signature is not list:  # type: ignore
                    result = [result]
                return E.xsd1(
                    "{0}Response".format(method),
                    *[
                        E.xsd1("listIndex{0}".format(i), str(part))
                        for i, part in enumerate(result)
                    ],
                )
            elif fn.response_named_signature:  # type: ignore
                return E.xsd1(
                    "{0}Response".format(method),
                    *[E.xsd1(key, str(result[key])) for key in result],
                )

        return cast(
            str,
            ET.tostring(E.soapenv.Envelope(E.soapenv.Body(_get_node(method, result)))),
        )

    @handlers.path("/(?P<service_name>\w*)\.(?P<request_type>\w*)")
    @handlers.methods("GET")
    def wsdl(
        self, request: Request, response: Response, service_name: str, request_type: str
    ) -> str:
        """
        This handles the request for WSDL or XSD documents. This is the
        entry point for most clients.
        """
        name = self.configuration.get("server.name", "SOAPServer")
        if service_name == name:
            if request_type == "wsdl":
                return decode(ET.tostring(self._generate_wsdl()))
            if request_type == "xsd":
                return decode(ET.tostring(self._generate_xsd()))
        raise NotFoundError(f"Unknown service {service_name}")

    @handlers.path("/services/(?P<service_name>\w*)")
    @handlers.methods("POST")
    def method_call(
        self, request: Request, response: Response, service_name: str
    ) -> str:
        """
        This will handle method calls of all registered methods.
        """

        method, args, kwargs = self.parse_method_call(request)
        setattr(request, "soap_method", method)
        result = self.dispatch(
            method, *(args if args else []), **(kwargs if kwargs else {})
        )
        response.headers["Content-Type"] = "application/soap+xml"
        return decode(
            self.format_response(result=result, request=request, response=response)
        )
