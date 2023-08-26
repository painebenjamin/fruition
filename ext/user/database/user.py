#!/usr/bin/env python3
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from pibble.ext.user.database.base import UserExtensionObjectBase


class User(UserExtensionObjectBase):
    __tablename__ = "pibble_user"

    id = Column(Integer, autoincrement=True, primary_key=True)

    username = Column(String, nullable=False, unique=True)
    verified = Column(Boolean, default=False)

    superuser = Column(Boolean, default=False)

    first_name = Column(String)
    last_name = Column(String)
    password = Column(String)
    password_expires = Column(DateTime)
    last_login = Column(DateTime)

User.Hide("password")
