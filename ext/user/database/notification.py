import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum

from pibble.ext.user.database.base import UserExtensionObjectBase
from pibble.ext.user.database.user import User


class Notification(UserExtensionObjectBase):
    __tablename__ = "pibble_user_notification"

    id = Column(Integer, autoincrement=True, primary_key=True)
    user_id = Column(
        Integer, User.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE")
    )

    notification_category = Column(
        Enum("error", "info", name="notification_category_enum"),
        default="info",
        nullable=False,
    )
    notification_message = Column(String)

    created = Column(DateTime, default=datetime.datetime.now)
