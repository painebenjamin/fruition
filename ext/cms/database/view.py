#!/usr/bin/env python3
from sqlalchemy import Column, String, ForeignKey, Integer, ForeignKeyConstraint
from sqlalchemy.types import JSON
from pibble.ext.cms.database.base import CMSExtensionObjectBase
from pibble.ext.cms.database.interface import (
    Taxonomy,
    Interface,
    InterfaceParameter,
)


class Taxon(CMSExtensionObjectBase):
    """
    Taxons are bound taxonomies, as create by users.
    """

    __tablename__ = "cms_taxon"

    id = Column(Integer, autoincrement=True, primary_key=True)
    parent_id = Column(
        Integer, ForeignKey("cms_taxon.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    taxonomy_name = Column(String(64), Taxonomy.ForeignKey("name"), nullable=False)

    value = Column(String(128), nullable=False)
    taxonomy = Taxonomy.Relationship()


Taxon.Relate(Taxon, name="parent", remote_side=Taxon.id, backref="children")


class View(CMSExtensionObjectBase):
    """
    Views are bound interfaces.
    """

    __tablename__ = "cms_view"

    id = Column(Integer, autoincrement=True, primary_key=True)
    interface_name = Column(
        String(64),
        Interface.ForeignKey("name", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )

    interface = Interface.Relationship()


class ViewTaxon(CMSExtensionObjectBase):
    """
    A taxon created bound to a view.
    """

    __tablename__ = "cms_view_taxon"

    view_id = Column(
        Integer,
        View.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    taxon_id = Column(
        Integer,
        Taxon.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )

    taxon = Taxon.Relationship()


View.Relate(ViewTaxon, name="taxa", backref="view")


class ViewParameter(CMSExtensionObjectBase):
    """
    All parameters necessary to construct the view.
    """

    __tablename__ = "cms_view_parameter"
    __table_args__ = (
        ForeignKeyConstraint(
            ["interface_name", "parameter_name"],
            ["cms_interface_parameter.interface_name", "cms_interface_parameter.name"],
        ),
    )

    view_id = Column(Integer, View.ForeignKey("id"), primary_key=True)
    interface_name = Column(String(64), primary_key=True)
    parameter_name = Column(String(64), primary_key=True)
    value = Column(JSON, default=None)

    parameter = InterfaceParameter.Relationship(
        foreign_keys=[interface_name, parameter_name]
    )


View.Relate(ViewParameter, name="parameters", backref="view")
