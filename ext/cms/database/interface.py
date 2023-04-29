from sqlalchemy import Column, String, Integer, Boolean
from sqlalchemy.types import JSON

from pibble.ext.cms.database.base import CMSExtensionObjectBase


class Taxonomy(CMSExtensionObjectBase):
    """
    Taxonomies are defined by applications, and allow for the definition
    of hierarchies.
    """

    __tablename__ = "cms_taxonomy"

    name = Column(String(64), primary_key=True)
    label = Column(String(128))
    hierarchical = Column(Boolean, default=False)
    active = Column(Boolean, default=True)


class Interface(CMSExtensionObjectBase):
    """
    Interfaces are defined by an application, and correspond to handlers.
    These are implemented into views. A view is therefore a bound interface.

    The goal of the interface class is to abstract what it is to be a view (page)
    or section of views (pages) on a website.

    An example of a set of interfaces is as follows, which roughly correspond to a
    wordpress-style blog::

      category = Taxonomy(name = "category", label = "Category")
      tag = Taxonomy(name = "tag", label = "Tag")

      page_interface = Interface(name = "page")
      page_title = InterfaceParameter(interface = page_interface.name, ptype = "string", label = "Title", required = True)
      page_content = InterfaceParameter(interface = page_interface.name, ptype = "template", label = "Page Content", required = True)

      page_category = InterfaceTaxonomy(taxonomy = category.name, interface = page_interface.name, label = "Categories", multiple = True, required = False)
      page_tag = InterfaceTaxonomy(taxonomy = tag.name, interface = page_interface.name, label = "Tags", multiple = True, required = False)

    """

    __tablename__ = "cms_interface"

    name = Column(String(64), primary_key=True)
    label = Column(String(128))
    active = Column(Boolean, default=True)


class InterfaceTaxonomy(CMSExtensionObjectBase):
    __tablename__ = "cms_interface_taxonomy"

    interface_name = Column(
        String(64),
        Interface.ForeignKey("name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    taxonomy_name = Column(
        String(64),
        Taxonomy.ForeignKey("name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )

    label = Column(String)

    multiple = Column(Boolean, default=False)
    required = Column(Boolean, default=False)

    index = Column(Integer, default=0)


Interface.Relate(InterfaceTaxonomy, name="taxonomies", backref="interface")
Taxonomy.Relate(InterfaceTaxonomy, name="interface_taxonomies", backref="taxonomy")


class InterfaceParameter(CMSExtensionObjectBase):
    __tablename__ = "cms_interface_parameter"

    interface_name = Column(
        String(64),
        Interface.ForeignKey("name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    name = Column(String(64), primary_key=True)

    ptype = Column(String, nullable=False)
    values = Column(JSON, default=[])

    label = Column(String(128))
    required = Column(Boolean, default=False)


Interface.Relate(InterfaceParameter, name="parameters", backref="interface")
