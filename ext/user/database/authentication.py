import datetime
from sqlalchemy import Column, Integer, String, DateTime
from pibble.ext.user.database.base import UserExtensionObjectBase
from pibble.ext.user.database.user import User


class AuthenticationToken(UserExtensionObjectBase):
    __tablename__ = "pibble_user_token"

    user_id = Column(
        User.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False
    )
    id = Column(Integer, autoincrement=True, primary_key=True)

    access_token = Column(String, unique=True)
    refresh_token = Column(String, unique=True)

    token_type = Column(String, default="Bearer")
    created = Column(DateTime, default=datetime.datetime.now)
    expires = Column(
        DateTime,
        default=lambda: datetime.datetime.now() + datetime.timedelta(hours=730),
    )


User.Relate(AuthenticationToken, name="tokens", backref="user")
