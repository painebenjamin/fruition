from __future__ import annotations

import sqlalchemy
import binascii
import os
import hashlib
import bcrypt

try:
    import pwd
    import spwd
except ImportError:
    pass

try:
    import crypt
except ImportError:
    pass
import collections
import sshpubkeys.keys
import paramiko.pkey
import traceback

try:
    import ldap
    from ldap.ldapobject import LDAPObject
except ImportError:
    LDAPObject = None

from pibble.util.strings import encode, decode, pretty_print
from pibble.util.log import logger

from pibble.database.engine import EngineFactory

from typing import Optional, Mapping, Union

from pibble.api.exceptions import (
    ConfigurationError,
    AuthenticationError,
    NotFoundError,
)
from pibble.api.configuration import APIConfiguration

LDAP_OPTIONS = [
    "OPT_API_FEATURE_INFO",
    "OPT_API_INFO",
    "OPT_CLIENT_CONTROLS",
    "OPT_DEBUG_LEVEL",
    "OPT_DEFBASE",
    "OPT_DEREF",
    "OPT_ERROR_STRING",
    "OPT_DIAGNOSTIC_MESSAGE",
    "OPT_HOST_NAME",
    "OPT_MATCHED_DN",
    "OPT_NETWORK_TIMEOUT",
    "OPT_PROTOCOL_VERSION",
    "OPT_REFERRALS",
    "OPT_REFHOPLIMIT",
    "OPT_RESTART",
    "OPT_SERVER_CONTROLS",
    "OPT_SIZELIMIT",
    "OPT_SUCCESS",
    "OPT_TIMELIMIT",
    "OPT_TIMEOUT",
    "OPT_URI",
]


class APIAuthenticationSource:
    """
    A helper class for servers looking to validate username/password authentication.

    Things like nonces and non u/p validation should be handled by the implementing class,
    but when simply looking to validate u/p, this can be used.

    :param configuration pibble.api.configuration.Configuration: The configuration from the server.
    """

    ENCRYPTIONS = [
        "plain",
        "md5",
        "sha1",
        "sha256",
        "sha384",
        "sha512",
        "blake2b",
        "blake2s",
        "sha3_224",
        "sha3_256",
        "sha3_512",
        "shake_128",
        "shake_256",
        "bcrypt",
        "crypt",
    ]

    def __init__(self, configuration: APIConfiguration):
        self.encryption = configuration.get("authentication.encryption", "md5")
        if self.encryption not in self.ENCRYPTIONS:
            raise ConfigurationError(
                "Encryption type '{0}' is not valid. Valid configuration values are one of ({1})".format(
                    self.encryption, pretty_print(self.ENCRYPTIONS)
                )
            )
        self.driver = APIAuthenticationSourceDriver.get_implementation(
            "authentication", self.encryption, configuration
        )

    def validate(self, username: str, password: str) -> None:
        """
        Validates the username and password against the stored values.

        :param username str: The username.
        :param password str: The password, either hashed or in plaintext.
        :raises AuthenticationError: When validation fails.
        """
        validated = False
        try:
            validated = self.driver._validate(username, password)
        except (NotFoundError, AuthenticationError):
            pass
        except Exception as ex:
            logger.error(
                "Receieved unexpected exception when validating username/password: {0}({1})".format(
                    type(ex).__name__, str(ex)
                )
            )
            logger.debug(traceback.format_exc())
            pass
        if not validated:
            raise AuthenticationError()

    def __getitem__(self, username: str) -> str:
        """
        Gets the password for a user.

        Not all implementations will provide a means for this (nor should they).
        """
        return str(self.driver._getPassword(username))


class APIAuthenticationSourceDriver:
    """
    A superclass that derived classes should inherit.

    Defines only one interface method, `validate(username, password)`, which
    returns True if valid, or false otherwise.
    """

    def __init__(self, encryption: str, configuration: APIConfiguration) -> None:
        self.encryption = encryption
        self.configuration = configuration

    @staticmethod
    def get_implementation(
        CONFIGURATION_PREFIX: str, encryption: str, configuration: APIConfiguration
    ) -> APIAuthenticationSourceDriver:
        drivername = configuration["{0}.driver".format(CONFIGURATION_PREFIX)]
        for cls in APIAuthenticationSourceDriver.__subclasses__():
            if getattr(cls, "AUTHENTICATION_DRIVERNAME", None) == drivername:
                return cls(encryption, configuration)
        raise ConfigurationError("Unknown authentication driver {0}".format(drivername))

    def _encryptPassword(self, password: str, stored: str) -> str:
        """
        Encrypts a plaintext password based on the provided algorithm.
        """
        if self.encryption == "crypt":
            if os.name == "nt":
                raise ConfigurationError("Crypt is not supported on Windows.")
            return crypt.crypt(password, stored)  # type: ignore
        else:
            return str(getattr(hashlib, self.encryption)(encode(password)).hexdigest())

    def _comparePassword(self, username: str, password: str) -> bool:
        """
        Compares a password using the configured method.
        """
        try:
            stored = self._getPassword(username)
            if self.encryption == "bcrypt":
                return bcrypt.checkpw(encode(stored), encode(password))
            elif self.encryption == "plain":
                return stored == password
            else:
                return self._encryptPassword(password, stored) == stored
        except KeyError:
            return False

    def _getPassword(self, username: str) -> str:
        """
        Gets the stored value for a username.
        """
        raise NotImplementedError()

    def _validate(self, username: str, password: str) -> bool:
        """
        Validates the username and password against the stored values.

        :param username str: The username.
        :param password str: The password, either hashed or in plaintext.
        :return bool: Whether or not the password validates.
        """
        return self._comparePassword(username, password)


class APIDatabaseAuthenticationSourceDriver(APIAuthenticationSourceDriver):
    AUTHENTICATION_DRIVERNAME = "database"
    CONFIGURATION_PREFIX = "authentication"

    def __init__(self, encryption: str, configuration: APIConfiguration):
        """
        A driver for database-backed authentication.

        Required configuration:
          1. ``authentication.database.type`` The database type - sqlite, postgresql, mssql, etc.
          2. ``authentication.database.connection`` The connection parameters. See :class:``pibble.database.engine.EngineFactory``.
          3. ``authentication.database.table`` The tablename to select from.

        Optional configuration:
          1. ``authentication.database.username`` The username key. Defaults to 'username'.
          2. ``authentication.database.pasword`` The password column. Defaults to 'password'.
        """
        self.encryption = encryption
        self.database_type = configuration["authentication.database.type"]
        self.database_configuration = configuration[
            "authentication.database.connection"
        ]
        self.tablename = configuration["authentication.database.table"]

        self.username = configuration.get(
            "authentication.database.username", "username"
        )
        self.password = configuration.get(
            "authentication.database.password", "password"
        )

        self.factory = EngineFactory(
            **{self.database_type: self.database_configuration}
        )
        self.engine = next(iter(self.factory[self.database_type]))
        self.metadata = sqlalchemy.MetaData(self.engine)

        self.table = sqlalchemy.Table(
            self.tablename, self.metadata, autoload=True, autoload_with=self.engine
        )

    def _getPassword(self, username: str) -> str:
        row = self.engine.execute(
            self.table.select().where(self.table.c[self.username] == username)
        ).first()
        if not row:
            raise KeyError(f"Cannot find password for username {username}")
        return str(row[self.password])


class RSAKeyAuthenticationSourceDriver(APIAuthenticationSourceDriver):
    """
    RSA key check authentication.

    Optional configuration:
    - `authentication.rsa.authorized` the path to the "authorized_keys" file. This can include unix home paths of "~" or "~home," which will be expanded using the authenticating username. Defaults to "~/.ssh/authorized_keys".
    - `authentication.rsa.directory` The directory to replace tilde (~) directives with, defaults to `/home/{username:s}`.
    """

    AUTHENTICATION_DRIVERNAME = "rsa"

    def __init__(self, encryption: str, configuration: APIConfiguration):
        self.configuration = configuration
        self.encryption = "rsa"
        self.authorized = self.configuration.get(
            "authentication.rsa.authorized", "~/.ssh/authorized_keys"
        )
        self.directory = self.configuration.get(
            "authentication.rsa.directory", "/home/{username:s}"
        )

    def _validate(
        self, username: str, key: Union[str, sshpubkeys.keys.SSHKey, paramiko.pkey.PKey]
    ) -> bool:
        directory = self.directory.format(username=username)
        authorized = self.authorized.replace("~user", directory).replace("~", directory)
        if isinstance(key, str):
            key = sshpubkeys.keys.SSHKey(key)
        if not os.path.exists(authorized):
            logger.debug(
                "Authorized key file {0} does not exist, abandoning authorization.".format(
                    authorized
                )
            )
            return False
        logger.debug(
            "Validating RSA using public authorized keyfile {0}".format(authorized)
        )
        with open(authorized, "r") as fp:
            keys = sshpubkeys.keys.AuthorizedKeysFile(fp)
        if isinstance(key, paramiko.pkey.PKey):
            key_hex = decode(binascii.hexlify(key.get_fingerprint()))
            key_hash = "MD5:{0}".format(
                ":".join(
                    [
                        "".join([key_hex[i * 2], key_hex[i * 2 + 1]])
                        for i in range(len(key_hex) // 2)
                    ]
                )
            )
        else:
            key_hash = key.hash_md5()
        for auth_key in keys.keys:
            if auth_key.hash_md5() == key_hash:
                return True
        return False


class UnixAuthenticationSourceDriver(APIAuthenticationSourceDriver):
    AUTHENTICATION_DRIVERNAME = "unix"

    def __init__(self, encryption: str, configuration: APIConfiguration):
        self.configuration = configuration
        self.encryption = "crypt"

    def _getPassword(self, username: str) -> str:
        if os.name == "nt":
            raise ConfigurationError("Cannot use Unix authentication on Windows")
        try:
            passwd = pwd.getpwnam(username)  # type: ignore
            if passwd[1] == "x" or passwd[1] == "*":
                return spwd.getspnam(username)[1]  # type: ignore
            else:
                return passwd[1]
        except KeyError:
            raise NotFoundError("Username {0} not found.".format(username))


class LDAPAuthenticationSourceDriver(APIAuthenticationSourceDriver):
    """
    Required Configuration:
      - `authentication.ldap.host` The host name or IP address of the LDAP server.
    Optional Configuration:
      - `authentication.ldap.method` Either "bind" or "search".
        - If "search", `authentication.ldap.admin` must contain admin login access credentials, i.e.:
          - `authentication.ldap.admin.cn` OR `authentication.ldap.admin.uid` OR `authentication.ldap.admin.username` (required)
          - `authentication.ldap.admin.password` (required, plaintext)
          - `authentication.ldap.admin.ou` (optional)
          - `authentication.ldap.admin.dc` (optional)
        - If "bind", no admin access is required, and a bind will be attempted with the user information.
      - `authentication.ldap.port` The port to connect to. Default 389 for non-TLS, and 636 for TLS.
      - `authentication.ldap.secure` Whether or not to use TLS. Default False.
      - `authentication.ldap.simple` Whether or not to use "simple" binding. Default True.
      - `authentication.ldap.domain` An optional domain to append to usernames during bind.
      - `authentication.ldap.ou` Organizational unit to search in.
      - `authentication.ldap.dc` Domain component(s) to search in.
      - `authentication.ldap.field` The field to search for the username in. Generally will either be `uid` or `cn`.
    """

    AUTHENTICATION_DRIVERNAME = "ldap"

    def __init__(self, encryption: str, configuration: APIConfiguration):
        super(LDAPAuthenticationSourceDriver, self).__init__(encryption, configuration)
        self.encryption = "crypt"
        self.host = self.configuration["authentication.ldap.host"]
        self.method = self.configuration.get("authentication.ldap.method", "bind")
        if self.method not in ["bind", "search"]:
            raise ConfigurationError(
                "LDAP authentication method must be 'bind' or 'search,' got '{0}.'".format(
                    self.method
                )
            )

        self.secure = self.configuration.get("authentication.ldap.secure", False)
        self.scheme = "ldaps" if self.secure else "ldap"
        self.port = self.configuration.get("authentication.ldap.port", None)
        self.address = "{0}://{1}".format(self.scheme, self.host)
        if self.port is not None:
            self.address = "{0}:{1}".format(self.address, self.port)

        logger.debug(
            "Configured using LDAP authentication address {0}, method {1}.".format(
                self.address, self.method
            )
        )

        self.simple = self.configuration.get("authentication.ldap.simple", True)
        self.domain = self.configuration.get("authentication.ldap.domain", None)
        self.options = self.configuration.get("authentication.ldap.options", {})
        self.ou = self.configuration.get("authentication.ldap.ou", None)
        self.dc = self.configuration.get("authentication.ldap.dc", None)
        self.field = self.configuration.get("authentication.ldap.field", "cn")

        self.adm_cn = self.configuration.get("authentication.ldap.admin.cn", None)
        self.adm_uid = self.configuration.get("authentication.ldap.admin.uid", None)
        self.adm_un = self.configuration.get("authentication.ldap.admin.username", None)
        self.adm_pw = self.configuration.get("authentication.ldap.admin.password", None)
        self.adm_ou = self.configuration.get("authentication.ldap.admin.ou", None)
        self.adm_dc = self.configuration.get("authentication.ldap.admin.dc", None)

        if self.method == "search":
            if self.simple and self.adm_un is None:
                raise ConfigurationError(
                    "Must include simple username (authentication.ldap.admin.username) when using 'search' authentication method with simple binding."
                )
            elif not self.simple and self.adm_cn is None and self.adm_uid is None:
                raise ConfigurationError(
                    "Must include either Common Name (authentication.ldap.admin.cn) or User ID (authentication.ldap.admin.uid) when using 'search' authentication method with non-simple binding."
                )
            elif self.adm_pw is None:
                raise ConfigurationError(
                    "Must include admin password (authentication.ldap.admin.password) when using 'search' authentication method."
                )

    def _getConnection(self) -> LDAPObject:
        if getattr(self, "_connection", None) is None:
            self._connection = ldap.initialize(self.address)
            for opt_name in self.options:
                if opt_name in LDAP_OPTIONS:
                    self._connection.set_option(
                        getattr(ldap, opt_name), self.options[opt_name]
                    )
                else:
                    logger.warning("Invalid option passed '{0}'".format(opt_name))
            for opt_name in LDAP_OPTIONS:
                try:
                    logger.debug(
                        "LDAP option {0}: {1}".format(
                            opt_name,
                            self._connection.get_option(getattr(ldap, opt_name)),
                        )
                    )
                except:
                    logger.warning(
                        "Could not retrieve LDAP option {0}".format(opt_name)
                    )

            if self.method == "search":
                dn = collections.OrderedDict()
                if self.adm_cn:
                    dn["cn"] = self.adm_cn
                elif self.adm_uid:
                    dn["uid"] = self.adm_uid
                if self.adm_ou:
                    dn["ou"] = self.adm_ou
                if self.adm_dc:
                    dn["dc"] = self.adm_dc
                try:
                    self._bindConnection(self.adm_un, self.adm_pw, dn)
                    logger.debug(
                        "Successfully bound connection to {0}".format(self.address)
                    )
                except Exception as ex:
                    raise ConfigurationError(
                        "Cannot bind using supplied admin credentials: {0}({1})".format(
                            type(ex).__name__, str(ex)
                        )
                    )
        return self._connection

    def _bindConnection(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        dn: Optional[Mapping] = None,
    ) -> None:
        conn = self._getConnection()
        if self.simple and username and password:
            if self.domain:
                logger.debug(
                    "LDAP performing simple bind with username {0}@{1}".format(
                        username, self.domain
                    )
                )
                conn.simple_bind_s("{0}@{1}".format(username, self.domain), password)
            else:
                logger.debug(
                    "LDAP performing simple bind with username {0}".format(username)
                )
                conn.simple_bind_s(username, password)
        elif dn:
            conn.bind_s(self._formatDistinguishedName(dn), password)
        else:
            raise ConfigurationError(
                "Must either use simple with username/password, or bind with a distinguished name."
            )

    def _getDistinguishedName(self, username: Optional[str] = None) -> Mapping:
        dn = collections.OrderedDict()
        if username is not None:
            dn[self.field] = username
        if self.ou is not None:
            dn["ou"] = self.ou
        if self.dc is not None:
            dn["dc"] = self.dc
        return dn

    def _formatDistinguishedName(self, dn: Mapping) -> str:
        return ",".join(
            [
                "{0}={1}".format(rdn, dn[rdn])
                if not isinstance(dn[rdn], list)
                else ",".join(["{0}={1}".format(rdn, rdn_part) for rdn_part in dn[rdn]])
                for rdn in dn
            ]
        )

    def _getPassword(self, username: str) -> str:
        if self.method != "search":
            raise ConfigurationError(
                "Cannot retrieve passwords when using 'bind' method."
            )
        conn = self._getConnection()
        dn = self._getDistinguishedName(username)
        try:
            result = conn.search_s(
                self._formatDistinguishedName(dn), ldap.SCOPE_SUBTREE
            )
            return decode(result[0][1]["userPassword"][0]).partition("}")[2]
        except ldap.NO_SUCH_OBJECT:
            raise NotFoundError("Username {0} not found.".format(username))

    def _validate(self, username: str, password: str) -> bool:
        if self.method == "bind":
            try:
                self._bindConnection(
                    username, password, self._getDistinguishedName(username)
                )
            except ldap.INVALID_DN_SYNTAX:
                raise ConfigurationError("Invalid DN syntax when validating password.")
            except ldap.INVALID_CREDENTIALS:
                return False
            return True
        else:
            return self._comparePassword(username, password)
