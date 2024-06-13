import os
import json

from typing import cast

from base64 import b64encode

from fruition.util.files import TempfileContext, dump_json, dump_yaml
from fruition.util.strings import Serializer, encode, decode
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion
from fruition.hooks.aws import lambda_action_handler, lambda_api_handler

from fruition.api.server.webservice.awslambda import (
    LambdaRequestPayloadV1,
    LambdaRequestContextV1,
    LambdaRequestPayloadV2,
    LambdaRequestContextV2,
)

JSONRPC_API_CONFIG = {
    "name": "TestAPI",
    "configuration": {
        "client": {
            "host": "127.0.0.1",
            "port": 9000,
            "classes": ["fruition.api.client.webservice.rpc.jsonrpc.JSONRPCClient"],
        },
        "server": {
            "driver": "werkzeug",
            "host": "0.0.0.0",
            "port": 9000,
            "classes": [
                "fruition.api.server.webservice.rpc.jsonrpc.JSONRPCServer",
                "fruition.api.server.webservice.awslambda.WebServiceAPILambdaServer",
            ],
            "functions": [
                {
                    "name": "getText",
                    "language": "python",
                    "register": True,
                    "script": "result = 'Hello, Lambda!'",
                }
            ],
        },
    },
}


def main() -> None:
    with DebugUnifiedLoggingContext():
        tempfiles = TempfileContext()
        with tempfiles as tempgen:
            json_config_path = tempfiles.touch("config.json")
            yml_config_path = tempfiles.touch("config.yml")

            dump_json(json_config_path, JSONRPC_API_CONFIG)
            dump_yaml(yml_config_path, JSONRPC_API_CONFIG)
            for config_path in [json_config_path, yml_config_path]:
                os.environ["FRUITION_CONFIG"] = config_path

                expected_json_rpc = {
                    "jsonrpc": "2.0",
                    "result": "Hello, Lambda!",
                    "id": 1,
                }

                payload_v1 = cast(
                    LambdaRequestPayloadV1,
                    {
                        "resource": "",
                        "path": "/RPC2",
                        "httpMethod": "POST",
                        "headers": {},
                        "multiValueHeaders": None,
                        "queryStringParameters": None,
                        "multiValueQueryStringParameters": None,
                        "requestContext": cast(
                            LambdaRequestContextV1,
                            {
                                "accountId": "",
                                "apiId": "",
                                "domainName": "",
                                "httpMethod": "POST",
                                "identity": None,
                                "path": "/RPC2",
                                "protocol": "",
                                "requestId": "",
                                "requestTime": "",
                                "requestTimeEpoch": 0,
                                "resourcePath": "",
                                "stage": "",
                            },
                        ),
                        "body": json.dumps(
                            {"jsonrpc": "2.0", "method": "getText", "id": 1}
                        ),
                        "isBase64Encoded": False,
                    },
                )

                payload_v2 = cast(
                    LambdaRequestPayloadV2,
                    {
                        "routeKey": "",
                        "rawPath": "/RPC2",
                        "rawQueryString": "",
                        "cookies": None,
                        "headers": {},
                        "queryStringParameters": None,
                        "requestContext": cast(
                            LambdaRequestContextV2,
                            {
                                "accountId": "",
                                "apiId": "",
                                "authentication": None,
                                "authorizer": None,
                                "domainName": "",
                                "requestId": "",
                                "routeKey": "",
                                "stage": "",
                                "time": "",
                                "timeEpoch": 0,
                                "http": {
                                    "method": "POST",
                                    "path": "/RPC2",
                                    "protocol": "",
                                    "sourceIp": "127.0.0.1",
                                    "userAgent": "fruition",
                                },
                            },
                        ),
                        "body": decode(
                            b64encode(
                                encode(
                                    json.dumps(
                                        {"jsonrpc": "2.0", "method": "getText", "id": 1}
                                    )
                                )
                            )
                        ),
                        "isBase64Encoded": True,
                    },
                )

                received_json_rpc = lambda_api_handler(payload_v1)
                Assertion(Assertion.EQ)(
                    expected_json_rpc, json.loads(received_json_rpc["body"])
                )

                received_json_rpc_2 = lambda_api_handler(payload_v2)
                Assertion(Assertion.EQ)(
                    expected_json_rpc, json.loads(received_json_rpc_2["body"])
                )

                lambda_action_handler({"action": "clean"})


if __name__ == "__main__":
    main()
