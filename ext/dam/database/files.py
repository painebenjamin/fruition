#!/usr/bin/env python3
from sqlalchemy import Column, String, Integer
from sqlalchemy.types import JSON
from pibble.ext.dam.database.base import DAMObjectBase


class MIMEMetaData(DAMObjectBase):
    __tablename__ = "dam_mime_metadata"

    mime_type = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(JSON, default=None)


class FileUpload(DAMObjectBase):
    __tablename__ = "dam_file_upload"

    path = Column(String, primary_key=True)

    label = Column(String)
    mime_type = Column(String)
    size = Column(Integer, default=0)


class FileUploadImage(DAMObjectBase):
    # Every single file upload has at least one image
    __tablename__ = "dam_file_upload_image"

    id = Column(Integer, autoincrement=True, primary_key=True)
    file_path = Column(
        FileUpload.ForeignKey("path", ondelete="RESTRICT", onupdate="RESTRICT")
    )

    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    size = Column(Integer, default=0)

    file_upload = FileUpload.Relationship()


FileUpload.Relate(FileUploadImage, name="images")
