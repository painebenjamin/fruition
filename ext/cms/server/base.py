from typing import Optional

from pibble.util.log import logger
from pibble.api.exceptions import ConfigurationError
from pibble.api.server.webservice.template import (
    TemplateServer,
    TemplateServerHandlerRegistry,
)
from pibble.api.middleware.database.orm import ORMMiddlewareBase
from pibble.ext.dam.server.base import DAMServerBase

from pibble.ext.cms.middleware import CMSExtensionContextMiddleware
from pibble.ext.cms.database import *


class CMSServerBase(
    TemplateServer, DAMServerBase, CMSExtensionContextMiddleware, ORMMiddlewareBase
):
    handlers = TemplateServerHandlerRegistry()

    def migrate_taxonomies(self) -> None:
        """
        Updates configured taxonomies in database at runtime
        """
        with self.orm.session() as session:
            taxonomies = session.query(self.orm.Taxonomy).all()

            for taxonomy in self.configuration["cms.taxonomies"]:
                if "name" not in taxonomy:
                    raise ConfigurationError("Taxonomies require a name.")

                name = taxonomy["name"]
                existing_list: list[Taxonomy] = [
                    t for t in taxonomies if t.name == name
                ]
                existing: Optional[Taxonomy] = (
                    None if not existing_list else existing_list[0]
                )

                if existing is not None:
                    logger.debug(f"Found existing taxonomy {name}, updating.")
                    existing.label = taxonomy.get("label", name)
                    existing.hierarchical = taxonomy.get("hierarchical", False)
                else:
                    logger.debug(f"Creating new taxonomy {name}.")
                    taxonomy_object = self.orm.Taxonomy(
                        name=name,
                        label=taxonomy.get("label", name),
                        active=True,
                        hierarchical=taxonomy.get("hierarchical", False),
                    )
                    session.add(taxonomy_object)
                    session.commit()

    def migrate_interfaces(self) -> None:
        """
        Updates configured interfaces in database at runtime
        """
        with self.orm.session() as session:
            interfaces = session.query(self.orm.Interface).all()
            for interface in self.configuration["cms.interfaces"]:
                if "name" not in interface:
                    raise ConfigurationError("Interfaces require a name.")

                name = interface["name"]
                label = interface.get("label", name)
                taxonomies = interface.get("taxonomies", [])
                parameters = interface.get("parameters", [])
                existing = [i for i in interfaces if i.name == name]

                if existing:
                    logger.debug(f"Found existing interface {name}, updating.")
                    interface_object = existing[0]
                    interface_object.label = label
                    interface_object.active = True
                else:
                    logger.debug(f"Creating new interface {name}.")
                    interface_object = self.orm.Interface(name=name, label=label)
                    session.add(interface_object)

                for taxonomy in interface_object.taxonomies:
                    configured = [
                        (i, t)
                        for i, t in enumerate(taxonomies)
                        if t.name == taxonomy["name"]
                    ]

                    if configured:
                        taxonomy.multiple = configured[0][1].get("multiple", False)
                        taxonomy.required = configured[0][1].get("required", False)
                        taxonomy.index = configured[0][0]
                    else:
                        session.remove(taxonomy)

                for i, taxonomy in enumerate(taxonomies):
                    if "name" not in taxonomy:
                        raise ConfigurationError(
                            "Taxonomies tied to an interface require a name."
                        )
                    if taxonomy["name"] not in [
                        t.name for t in interface_object.taxonomies
                    ]:
                        session.add(
                            self.orm.InterfaceTaxonomy(
                                interface_name=name,
                                taxonomy_name=taxonomy["name"],
                                label=taxonomy.get("label", taxonomy["name"]),
                                multiple=taxonomy.get("multiple", False),
                                required=taxonomy.get("required", False),
                                index=i,
                            )
                        )

                for parameter in interface_object.parameters:
                    configured = [p for p in parameters if p.name == parameter["name"]]

                    if configured:
                        parameter["ptype"] = configured[0].ptype  # type: ignore
                        parameter["required"] = configured[0].required  # type: ignore
                        parameter["label"] = configured[0].label  # type: ignore
                    else:
                        session.remove(parameter)

                for parameter in parameters:
                    if parameter["name"] not in [
                        p.name for p in interface_object.parameters
                    ]:
                        session.add(
                            self.orm.InterfaceParameter(
                                interface_name=name,
                                name=parameter["name"],
                                ptype=parameter["ptype"],
                                label=parameter.get("label", parameter["name"]),
                                required=parameter.get("required", False),
                                values=parameter.get("values", []),
                            )
                        )

            session.commit()

    def on_configure(self) -> None:
        """
        Look for configured views, update database if necessary.
        """
        self.orm.extend_base(
            CMSExtensionObjectBase,
            force=self.configuration.get("orm.force", False),
            create=self.configuration.get("orm.create", True),
        )
        if "cms.taxonomies" in self.configuration:
            logger.debug("Migrating taxonomies.")
            self.migrate_taxonomies()
        if "cms.interfaces" in self.configuration:
            logger.debug("Migrating interfaces.")
            self.migrate_interfaces()
