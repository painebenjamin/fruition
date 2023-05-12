import sys
import click
import termcolor
import logging
import code
import requests
import multiprocessing
import time
import traceback

from typing import Optional, List

from pibble.api.meta.helpers import MetaFactory, MetaService
from pibble.util.log import (
    logger,
    LevelUnifiedLoggingContext,
    DebugUnifiedLoggingContext,
    ConfigurationLoggingContext,
)
from pibble.util.files import load_json


class MetaServerProcess(multiprocessing.Process):
    def __init__(self, service: MetaService) -> None:
        super(MetaServerProcess, self).__init__()
        self.service = service
        self.name = self.service.name

    def run(self) -> None:
        self.service.serve()


@click.group(name="pibble")
def main() -> None:
    """
    Pibble Framework command-line tools.
    """
    pass


@main.command(short_help="Start a server based on configuration.")
@click.argument("configuration")
@click.option(
    "--debug", is_flag=True, help="Turn on debug unified logging.", default=False
)
@click.option(
    "--interactive",
    is_flag=True,
    help="After instantiation, enter an interactive console instead of serving.",
    default=False,
)
def server(configuration: str, debug: bool = False, interactive: bool = False) -> None:
    """
    Starts a server, synchronously, using a configuration file.

    The configuration file format is specified by its extension (.yml/.yaml being YAML, .json being JSON). No other formats are accepted.
    """
    factory = MetaFactory.from_file(configuration)

    if debug:
        context = DebugUnifiedLoggingContext()
    else:
        context = ConfigurationLoggingContext(factory.api_configuration)  # type: ignore

    with context:
        service = factory("server")
        if interactive:
            print(
                termcolor.colored(
                    "Entering console. Use global object 'server' as instantiated server.",
                    "cyan",
                )
            )
            code.interact(local={"server": service.instance})
        else:
            try:
                service.serve()
            finally:
                service.destroy()


@main.command(short_help="Start multiple servers based on configurations.")
@click.argument("configuration", nargs=-1)
@click.option(
    "--debug", is_flag=True, help="Turn on debug unified logging.", default=False
)
def servers(configuration: List[str], debug: bool = False) -> None:
    """
    Starts servers, synchronously, using a configuration file.

    All servers will be ran at the same time, and stopped at the same time.
    If any server errors, all will be stopped.

    The configuration file format is specified by its extension (.yml/.yaml being YAML, .json being JSON). No other formats are accepted.
    """

    services: List[MetaServerProcess] = []

    for config in configuration:
        factory = MetaFactory.from_file(config)
        meta_service = factory("server")
        services.append(MetaServerProcess(meta_service))

    if debug:
        context = DebugUnifiedLoggingContext()
    else:
        context = ConfigurationLoggingContext(factory.api_configuration)  # type: ignore

    with context:
        try:
            for service in services:
                logger.info("Starting {0}".format(service.name))
                time.sleep(1)
                service.daemon = False
                service.start()
            while all([service.is_alive() for service in services]):
                time.sleep(1)
            for service in services:
                if not service.is_alive():
                    logger.error("Service {0} died, exiting.".format(service.name))
        except Exception as ex:
            logger.error(
                "Received exception: {0}({1})".format(type(ex).__name__, str(ex))
            )
            logger.debug(traceback.format_exc())
        finally:
            for service in services:
                logger.info("Stopping {0}".format(service.name))
                service.terminate()


@main.command(short_help="Start a client based on configuration.")
@click.argument("configuration")
@click.option(
    "-c",
    "--command",
    help="A command to execute. If passed, will not be interactive.",
    default=None,
)
@click.option(
    "-a",
    "--arg",
    help="Arguments to pass into the command specified by -c.",
    multiple=True,
)
@click.option(
    "-j",
    "--json",
    help="JSON Formatted keyword arugments to pass into the command specifid by -c.",
    default=None,
)
@click.option(
    "-w",
    "--wrapper",
    help="Whether or not to use an AWS Lambda wrapper.",
    is_flag=True,
    default=False,
)
@click.option(
    "--long/--short",
    help="Truncate or don't truncate responses from commands.",
    default=False,
)
@click.option(
    "--debug", is_flag=True, help="Turn on debug unified logging.", default=False
)
def client(
    configuration: str,
    command: Optional[str] = None,
    arg: Optional[List[str]] = None,
    json: Optional[str] = None,
    wrapper: bool = False,
    long: bool = False,
    debug: bool = False,
) -> None:
    """
    Initiates a client from a configuration file.

    The configuration file format is specified by its extension (.yml/.yaml being YAML, .json being JSON). No other formats are accepted.

    Use -c/--command to pass a command into the client after instantiation. See -h/--help for other options concerning command usage. Not passing in a command will enter into an interactive shell.
    """

    factory = MetaFactory.from_file(configuration)

    if wrapper:
        wrapper_path = (
            "pibble.api.client.webservice.wrapper.WebServiceAPILambdaClientWrapper"
        )
        if (
            wrapper_path
            not in factory.configuration["configuration"]["client"]["classes"]
        ):
            factory.configuration["configuration"]["client"]["classes"].append(
                wrapper_path
            )
    if debug:
        context = DebugUnifiedLoggingContext()
    else:
        context = ConfigurationLoggingContext(factory.api_configuration)  # type: ignore

    with context:
        client = factory("client")
        if command is not None:
            if json is not None:
                kwargs = load_json(json)
            else:
                kwargs = {}
            args = tuple() if arg is None else arg
            if type(kwargs) is not dict:
                print(
                    termcolor.colored(
                        "JSON doesn't evaluate to an object; it's best if you use a mapping. Passing this as 'value'.",
                        "yellow",
                    )
                )
                kwargs = {"value": kwargs}
            response = client(command, *args, **kwargs)
            if isinstance(response, requests.Response):
                print(
                    termcolor.colored("HTTP {0}".format(response.status_code), "green")
                )
                response = response.text
                if not long:
                    response = response.splitlines()
                    total_lines = len(response)
                    print(termcolor.colored("\n".join(response[:10]), "cyan"))
                    if total_lines > 10:
                        print(
                            "...and {0} more lines (use --long to not truncate.)".format(
                                total_lines - 10
                            )
                        )
                else:
                    print(termcolor.colored(response, "cyan"))
            else:
                print(response)
        else:
            print(
                termcolor.colored(
                    "Entering console. Use global object 'client' as instantiated client.",
                    "cyan",
                )
            )
            code.interact(local={"client": client})


@main.command(short_help="Generates a thumbnail of most kinds of files.")
@click.argument("input")
@click.argument("output")
@click.option(
    "--debug", is_flag=True, help="Turn on debug unified logging.", default=False
)
@click.option(
    "--trim", is_flag=True, help="Trim whitespace around the result.", default=False
)
@click.option(
    "-w", "--width", help="The width of the thumbnail. Defaults to 128.", default=128
)
@click.option(
    "-h", "--height", help="The height of the thumbnail. Defaults to 128.", default=128
)
def thumbnail(
    input: str,
    output: str,
    debug: bool = False,
    trim: bool = False,
    width: int = 128,
    height: int = 128,
) -> None:
    """
    Builds a thumbnail from an input path.
    """
    with LevelUnifiedLoggingContext(logging.DEBUG if debug else logging.WARNING):
        from pibble.media.thumbnail import ThumbnailBuilder

        ThumbnailBuilder(input).build(output, width, height, trim=trim)


try:
    main()
except Exception as ex:
    print(termcolor.colored(str(ex), "red"))
    if "--debug" in sys.argv:
        print(termcolor.colored(traceback.format_exc(), "red"))
    sys.exit(5)
sys.exit(0)
