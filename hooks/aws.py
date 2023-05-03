import os
import sys
import json
import yaml
import logging
import traceback

from typing import Optional, Union, Any, cast

from pibble.util.helpers import qualify, resolve, FlexibleJSONDecoder
from pibble.resources.retriever import Retriever
from pibble.database.orm import ORMBuilder
from pibble.api.meta.helpers import MetaFactory, MetaService
from pibble.api.server.webservice.awslambda import (
    LambdaRequestPayloadV1,
    LambdaRequestPayloadV2,
    LambdaResponseDict,
    LambdaContext,
    WebServiceAPILambdaServer,
)

# Set default log handler and level
logger = logging.getLogger("pibble-aws-hooks")
lambda_log_handler = logging.StreamHandler(sys.stdout)
lambda_log_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s (%(filename)s:%(lineno)s) %(message)s"
    )
)
logger.setLevel(logging.DEBUG)
logger.addHandler(lambda_log_handler)

service: Optional[MetaService] = None


def debug_mode() -> bool:
    """
    Checks if the debug environment variable is set.
    """
    debug_str = os.environ.get("PIBBLEDEBUG", None)
    return isinstance(debug_str, str) and debug_str.lower()[0] in ["t", "y", "1"]


def get_config_from_file(config_file: str) -> Any:
    """
    Loads config from a file.

    Supports any protocol supported by the retriever (file, http, s3, ftp, sftp, etc.)
    """
    logger.debug(f"Retrieving configuration file {config_file}")
    retriever = Retriever.get(config_file)
    config_string = retriever.all()

    if retriever.extension in [".yml", ".yaml"]:
        logger.debug("Parsing configuration as YML")
        return yaml.safe_load(config_string)
    else:
        logger.debug("Parsing configuration as JSON")
        return json.loads(config_string, cls=FlexibleJSONDecoder)


def try_load_service() -> None:
    """
    Attempts to read the configuration from the environment,
    and instantiate the metaservice.
    """
    global service
    config_file = os.environ.get("PIBBLECONFIG", None)
    if config_file is None:
        raise OSError("No configuration available.")

    config = get_config_from_file(config_file)

    if (
        WebServiceAPILambdaServer not in config["configuration"]["server"]["classes"]
        and qualify(WebServiceAPILambdaServer)
        not in config["configuration"]["server"]["classes"]
    ):
        config["configuration"]["server"]["classes"].append(WebServiceAPILambdaServer)

    factory = MetaFactory(config)
    service = factory("server")
    logger.debug("Successfully instantiated server.")


def lambda_action_handler(event: dict, context: Optional[LambdaContext] = None) -> str:
    """
    This secondary lambda handler exposes a small handful of functions that may wish to be
    called by external services.
    """
    action = event.get("action", None)
    config_file = event.get("config", None)

    if action is None:
        return "No action supplied."

    if action == "clean":
        global service
        if service is not None:
            service.destroy()
            del service
            service = None
            return "Cleaned."
        return "Nothing to clean."
    elif action in ["migrate", "force-migrate"]:
        if config_file is None:
            return "No config supplied."
        config = get_config_from_file(config_file)
        try:
            orm = ORMBuilder(config["type"], config["connection"], migrate=False)
            for classname in config["classes"]:
                orm.extend_base(resolve(classname), create=False)
            orm.migrate(action == "force-migrate")
        except KeyError as ex:
            return f"Missing required configuration key {ex}"
        return "Migrate success."
    return f"Unknown action {action}"


def lambda_api_handler(
    event: Union[LambdaRequestPayloadV1, LambdaRequestPayloadV2],
    context: Optional[LambdaContext] = None,
) -> LambdaResponseDict:
    """
    The lambda handler uses a global service object. When warm, this service object will remain
    initialized. Once the lambda function goes cold, it will be reset to empty.
    """
    global service
    try:
        if service is None:
            logger.debug("Service doesn't exist, attempting to load.")
            try_load_service()
    except Exception as ex:
        if debug_mode():
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "multiValueHeaders": {},
                "body": json.dumps(
                    {
                        "exception": type(ex).__name__,
                        "message": str(ex),
                        "traceback": traceback.format_exc().splitlines(),
                        "event": event,
                    }
                ),
            }
    if service is not None:
        try:
            logger.debug("Service loaded, handling lambda request.")
            return cast(
                LambdaResponseDict, service.handle_lambda_request(event, context)
            )
        except Exception as ex:
            if debug_mode():
                return {
                    "statusCode": 500,
                    "multiValueHeaders": {},
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(
                        {
                            "exception": type(ex).__name__,
                            "message": str(ex),
                            "traceback": traceback.format_exc().splitlines(),
                            "event": event,
                        }
                    ),
                }
            return {
                "statusCode": 500,
                "headers": {},
                "multiValueHeaders": {},
                "body": "An unhandled exception occurred.",
            }
    logger.error("Servier could not be created.")
    return {
        "statusCode": 503,
        "headers": {},
        "multiValueHeaders": {},
        "body": "This service could not be initialized.",
    }
