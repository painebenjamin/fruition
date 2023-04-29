#!/usr/bin/env python3
from sqlalchemy import Column, String, Integer, Sequence
from sqlalchemy.types import JSON

from pibble.ext.cms.database.base import CMSExtensionObjectBase
from pibble.ext.dam.database import FileUpload


class Menu(CMSExtensionObjectBase):
    __tablename__ = "cms_menu"

    id = Column(Integer, Sequence("menu_id_sequence"), primary_key=True)


class MenuLocation(CMSExtensionObjectBase):
    __tablename__ = "cms_menu_location"

    name = Column(String, primary_key=True)
    menu_id = Column(Menu.ForeignKey("id", ondelete="SET NULL", onupdate="CASCADE"))

    menu = Menu.Relationship()


class MenuItem(CMSExtensionObjectBase):
    __tablename__ = "cms_menu_item"

    menu_id = Column(
        Integer,
        Menu.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    submenu_id = Column(
        Integer, Menu.ForeignKey("id", ondelete="SET NULL", onupdate="CASCADE")
    )

    label = Column(String, nullable=False)
    item_type = Column(String, nullable=False)

    view_name = Column(String)
    view_args = Column(JSON)

    url = Column(String)
    upload_path = Column(
        FileUpload.ForeignKey("path", ondelete="SET NULL", onupdate="CASCADE")
    )

    sub_menu = Menu.Relationship(foreign_keys=[submenu_id])
    file_upload = FileUpload.Relationship()


Menu.Relate(MenuItem, name="MenuItems", foreign_keys=[MenuItem.menu_id], backref="menu")
