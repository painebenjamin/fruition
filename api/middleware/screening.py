import os
import ipaddress

from typing import List, Union

from pibble.util.log import logger
from pibble.util.files import load_yaml, load_json
from pibble.api.middleware.base import APIMiddlewareBase
from pibble.api.configuration import APIConfiguration


def parse_ip_list(
    configuration: APIConfiguration, key: str
) -> List[ipaddress.IPv4Network]:
    """
    Parses the list of IP addresses into valid ipaddress.IPv4Network's.

    :param configuration APIConfiguration: The server's configuration.
    :param key str: The configuration get to get out of the APIConfiguration.
    :returns list: The list of IP address network values.
    """
    ip_list_config: Union[List[str], str] = configuration.get(key, [])
    ip_str_list: List[str] = []
    ip_list: List[ipaddress.IPv4Network] = []

    if isinstance(ip_list_config, str):
        if os.path.exists(ip_list_config):
            if ip_list_config.endswith(".yml") or ip_list_config.endswith(".yaml"):
                yaml_ip_list = load_yaml(ip_list_config)
                if not isinstance(yaml_ip_list, list):
                    raise ValueError(f"{ip_list_config} is not an array")
                ip_str_list = [str(yaml_ip) for yaml_ip in yaml_ip_list]
            elif ip_list_config.endswith(".json"):
                json_ip_list = load_json(ip_list_config)
                if not isinstance(json_ip_list, list):
                    raise ValueError(f"{ip_list_config} is not an array")
                ip_str_list = [str(json_ip) for json_ip in json_ip_list]
            else:
                ip_str_list = open(ip_list_config, "r").readlines()
        else:
            logger.info(
                "IPlist {0} ({1}) is a string and not a file pointer, defaulting to this as a list.".format(
                    ip_list_config, key
                )
            )
            ip_str_list = [ip_list_config]
    elif isinstance(ip_list_config, list):
        ip_str_list = [str(item) for item in ip_list_config]

    for ip_addr in ip_str_list:
        try:
            ip_list.append(ipaddress.IPv4Network(ip_addr))
        except Exception as ex:
            logger.error(
                "Cannot parse IPv4 Address '{0}', skipping.\n{1}()\n{2}".format(
                    ip_addr, type(ex).__name__, str(ex)
                )
            )

    return ip_list


class ScreeningAPIMiddlewareBase(APIMiddlewareBase):
    """
    Performs IP-Address based screening on inbound requests.

    This allows for the following configuration:

    1. ``server.allowlist`` Either a list of IP addresses (list) or a file. If it's a file, this will read that file. These are always allowed to proceed. Defaults to empty.
    2. ``server.blocklist`` Similar to ``server.allowlist``, but these are always rejected. Defaults to empty.
    3. ``server.offlist`` What the default behavior is. This is either `accept` or `reject`. Defaults to `accept`.

    :param request pibble.api.server.thrift.ThriftRequest: The request object.
    """

    def on_configure(self) -> None:
        self.allowlist = parse_ip_list(self.configuration, "server.allowlist")
        logger.debug("Allowlist set to {0}.".format(self.allowlist))
        self.blocklist = parse_ip_list(self.configuration, "server.blocklist")
        logger.debug("Blocklist set to {0}.".format(self.blocklist))

        self.offlist = self.configuration.get("server.offlist", "accept")
        if self.offlist not in ["accept", "reject"]:
            logger.error(
                "Offlist configuration '{0}' not in ['accept', 'reject']. Defaulting to 'accept'.".format(
                    self.offlist
                )
            )
            self.offlist = "accept"
