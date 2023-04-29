import os
import yaml
import json
import ipaddress

from pibble.util.log import logger
from pibble.api.middleware.base import APIMiddlewareBase
from pibble.api.configuration import APIConfiguration


def ParseList(configuration: APIConfiguration, key: str) -> list[ipaddress.IPv4Network]:
    """
    Parses the list of IP addresses into valid ipaddress.IPv4Network's.

    :param configuration APIConfiguration: The server's configuration.
    :param key str: The configuration get to get out of the APIConfiguration.
    :returns list: The list of IP address network values.
    """
    iplist = configuration.get(key, [])

    if isinstance(iplist, str):
        if os.path.exists(iplist):
            if iplist.endswith(".yml") or iplist.endswith(".yaml"):
                iplist = yaml.load(open(iplist, "r"), Loader=yaml.BaseLoader)
            elif iplist.endswith(".json"):
                iplist = json.load(open(iplist, "r"))
            else:
                iplist = open(iplist, "r").readlines()
        else:
            logger.info(
                "IPlist {0} ({1}) is a string and not a file pointer, defaulting to this as a list.".format(
                    iplist, key
                )
            )
            iplist = [iplist]

    for i, ipaddr in enumerate(iplist):
        try:
            iplist[i] = ipaddress.IPv4Network(ipaddr)
        except Exception as ex:
            logger.error(
                "Cannot parse IPv4 Address '{0}', skipping.\n{1}()\n{2}".format(
                    ipaddr, type(ex).__name__, str(ex)
                )
            )
            iplist[i] = None
    return [ipaddr for ipaddr in iplist if ipaddr is not None]


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
        self.allowlist = ParseList(self.configuration, "server.allowlist")
        logger.debug("Allowlist set to {0}.".format(self.allowlist))
        self.blocklist = ParseList(self.configuration, "server.blocklist")
        logger.debug("Blocklist set to {0}.".format(self.blocklist))

        self.offlist = self.configuration.get("server.offlist", "accept")
        if self.offlist not in ["accept", "reject"]:
            logger.error(
                "Offlist configuration '{0}' not in ['accept', 'reject']. Defaulting to 'accept'.".format(
                    self.offlist
                )
            )
            self.offlist = "accept"
