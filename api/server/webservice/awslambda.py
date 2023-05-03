from typing import TypedDict, Optional, Union, Dict, List, Any, cast
from base64 import b64decode
from urllib.parse import parse_qs

from pibble.util.log import logger
from pibble.util.strings import encode

from pibble.api.exceptions import ConfigurationError
from pibble.api.server.webservice.base import WebServiceAPIServerBase
from pibble.api.helpers.wrappers import RequestWrapper, ResponseWrapper

# V1


class LambdaRequestContextV1(TypedDict):
    accountId: str
    apiId: str
    domainName: str
    httpMethod: str
    identity: Optional[Dict[str, Any]]
    path: str
    protocol: str
    requestId: str
    requestTime: str
    requestTimeEpoch: int
    resourcePath: str
    stage: str


class LambdaRequestPayloadV1(TypedDict):
    resource: str
    path: str
    httpMethod: str
    headers: Dict[str, str]
    multiValueHeaders: Optional[Dict[str, List[str]]]
    queryStringParameters: Optional[Dict[str, str]]
    multiValueQueryStringParameters: Optional[Dict[str, List[str]]]
    requestContext: LambdaRequestContextV1
    body: Optional[str]
    isBase64Encoded: Optional[bool]


# V2


class LambdaRequestContextV2HTTP(TypedDict):
    method: str
    path: str
    protocol: str
    sourceIp: str
    userAgent: str


class LambdaRequestContextV2(TypedDict):
    accountId: str
    apiId: str
    authentication: Optional[Dict[str, Any]]
    authorizer: Optional[Dict[str, Any]]
    domainName: str
    http: LambdaRequestContextV2HTTP
    requestId: str
    routeKey: str
    stage: str
    time: str
    timeEpoch: int


class LambdaRequestPayloadV2(TypedDict):
    routeKey: str
    rawPath: str
    rawQueryString: str
    cookies: Optional[List[str]]
    headers: Dict[str, str]
    queryStringParameters: Optional[Dict[str, str]]
    requestContext: LambdaRequestContextV2
    body: Optional[str]
    isBase64Encoded: Optional[bool]


# Common


class LambdaResponseDict(TypedDict):
    statusCode: int
    headers: Dict[str, str]
    multiValueHeaders: Dict[str, List[str]]
    body: str


class LambdaContext:
    function_name: str
    function_version: str
    invoked_function_arn: str
    memory_limit_in_mb: int
    aws_request_id: str
    log_group_name: str
    log_stream_name: str


class WebServiceAPILambdaServer(WebServiceAPIServerBase):
    """
    Provides an easy function for getting a lambda handler.
    """

    def handle_lambda_request(
        self,
        event: Union[LambdaRequestPayloadV1, LambdaRequestPayloadV2],
        context: Optional[LambdaContext] = None,
    ) -> LambdaResponseDict:
        logger.debug(f"Receiving lambda request {event}")
        try:
            # Declare base variables to parse from differing payload
            parameters: Dict[str, Union[str, List[str]]] = {}
            body: Optional[bytes] = None
            user_agent: Optional[str] = None
            http_method: str = ""
            remote_addr: str = ""
            path: str = ""

            # Common between payload types
            headers: Dict[str, str] = event["headers"]

            if event.get("body", None) is not None:
                body_str = cast(str, event["body"])
                if event.get("isBase64Encoded", False):
                    body = b64decode(body_str)
                else:
                    body = encode(body_str)

            # Evaluate payload
            use_v2 = event.get("version", None) == "2.0" or "routeKey" in event

            logger.debug(
                "Parsing version {0} payload".format("2.0" if use_v2 else "1.0")
            )
            if use_v2:
                # v2.0 Payload
                payload_v2 = cast(LambdaRequestPayloadV2, event)

                http_method = payload_v2["requestContext"]["http"]["method"]
                path = payload_v2["requestContext"]["http"]["path"]
                user_agent = payload_v2["requestContext"]["http"]["userAgent"]
                remote_addr = payload_v2["requestContext"]["http"]["sourceIp"]

                if payload_v2.get("cookies", None) is not None:
                    headers["cookie"] = ";".join(cast(List[str], payload_v2["cookies"]))

                if payload_v2.get("rawQueryString", None) is not None:
                    parsed_parameters = parse_qs(payload_v2["rawQueryString"])
                    parameters.update(
                        dict(
                            [
                                (
                                    key,
                                    parsed_parameters[key][0]
                                    if len(parsed_parameters[key]) == 0
                                    else parsed_parameters[key],
                                )
                                for key in parsed_parameters
                            ]
                        )
                    )

            else:
                # v1.0 Payload
                payload_v1 = cast(LambdaRequestPayloadV1, event)

                http_method = payload_v1["httpMethod"]
                path = payload_v1["path"]

                if payload_v1.get("multiValueQueryStringParameters", None) is not None:
                    payload_params = cast(
                        Dict[str, List[str]],
                        payload_v1["multiValueQueryStringParameters"],
                    )
                    parameters.update(
                        dict(
                            [
                                (
                                    key,
                                    payload_params[key][0]
                                    if len(payload_params[key]) == 0
                                    else payload_params[key],
                                )
                                for key in payload_params
                            ]
                        )
                    )

                if payload_v1["requestContext"].get("identity", None) is not None:
                    identity_dict = cast(dict, payload_v1["requestContext"]["identity"])
                    user_agent = identity_dict.get("userAgent", "")
                    remote_addr = identity_dict.get("sourceIp", "")

            request = RequestWrapper(
                http_method,
                path,
                params=parameters,
                user_agent=user_agent,
                headers=headers,
                remote_addr=remote_addr,
                body=body,
            )

            response = ResponseWrapper()
            self.handle_request(request, response)

            return {
                "statusCode": response.status_code,
                "headers": dict(
                    [
                        (key, response.headers[key])
                        for key in response.headers
                        if not isinstance(response.headers[key], list)
                    ]
                ),
                "multiValueHeaders": dict(
                    [
                        (key, response.headers[key])
                        for key in response.headers
                        if isinstance(response.headers[key], list)
                    ]
                ),
                "body": response.text,
            }
        except KeyError as ex:
            raise ConfigurationError(f"Required API gateway variable {ex} not present.")
