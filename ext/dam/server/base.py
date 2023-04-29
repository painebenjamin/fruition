from pibble.api.server.webservice.base import (
    WebServiceAPIServerBase,
)
from pibble.api.middleware.database.orm import ORMMiddlewareBase
from pibble.ext.dam.database.base import DAMObjectBase


class DAMServerBase(WebServiceAPIServerBase, ORMMiddlewareBase):
    def on_configure(self) -> None:
        self.orm.extend_base(
            DAMObjectBase,
            force=self.configuration.get("orm.force", False),
            create=self.configuration.get("orm.create", True),
        )
