import sqlalchemy

from fruition.database.orm import (
    ORMObjectBase,
    ORMBuilder,
    ORMEncryptedStringType,
    ORMVariadicType,
    ORMEncryptedVariadicType,
    ORM,
)
from fruition.util.log import DebugUnifiedLoggingContext
from fruition.util.helpers import Assertion, expect_exception
from fruition.api.exceptions import BadRequestError, PermissionError


class ORMTestBase(ORMObjectBase):
    pass


class Page(ORMTestBase):
    __tablename__ = "page"

    id = sqlalchemy.Column(
        sqlalchemy.Integer, sqlalchemy.Sequence("page_id_sequence"), primary_key=True
    )
    text = sqlalchemy.Column(sqlalchemy.Text)
    password = sqlalchemy.Column(sqlalchemy.String, nullable=True)  # Hidden column
    encrypted_field = sqlalchemy.Column(ORMEncryptedStringType)  # Two-way encrypt
    variadic_field = sqlalchemy.Column(ORMVariadicType)
    variadic_encrypted = sqlalchemy.Column(ORMEncryptedVariadicType)


Page.Hide(columns=["password"])


class Keyword(ORMTestBase):
    __tablename__ = "keyword"

    id = sqlalchemy.Column(
        sqlalchemy.Integer, sqlalchemy.Sequence("keyword_id_sequence"), primary_key=True
    )
    name = sqlalchemy.Column(sqlalchemy.String)


class KeywordRelationship(ORMTestBase):
    keyword_id = sqlalchemy.Column(
        Keyword.ForeignKey("id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    id = sqlalchemy.Column(
        sqlalchemy.Integer, sqlalchemy.Sequence("keyword_id_sequence"), primary_key=True
    )
    keyword = Keyword.Relationship(backref="hidden_relationships")


Keyword.Hide(relationships=["hidden_relationships"])


class PageKeywords(ORMTestBase):
    __tablename__ = "page_keywords"

    page_id = sqlalchemy.Column(Page.ForeignKey("id"), primary_key=True)
    keyword_id = sqlalchemy.Column(Keyword.ForeignKey("id"), primary_key=True)

    page = Page.Relationship(backref="PageKeywords")
    keyword = Keyword.Relationship(backref="PageKeywords")


def test_oop(orm: ORM) -> None:
    with orm.session() as session:
        page_1 = session.add(
            orm.Page(
                text="text1",
                encrypted_field="encrypted1",
                variadic_field=True,
                variadic_encrypted=4,
            )
        )
        page_2 = session.add(
            orm.models["Page"](
                text="text2",
                encrypted_field="encrypted2",
                variadic_field=10.0,
                variadic_encrypted=[None, "null", {"key": []}],
            )
        )  # Other syntax

        session.commit()

        keyword_1 = session.add(orm.Keyword(name="keyword1"))
        keyword_2 = session.add(orm.Keyword(name="keyword2"))
        keyword_3 = session.add(orm.Keyword(name="keyword3"))

        session.commit()

        pk_1 = session.add(orm.PageKeywords(page_id=page_1.id, keyword_id=keyword_1.id))
        pk_2 = session.add(orm.PageKeywords(page_id=page_1.id, keyword_id=keyword_2.id))
        pk_3 = session.add(orm.PageKeywords(page_id=page_2.id, keyword_id=keyword_1.id))
        pk_4 = session.add(orm.PageKeywords(page_id=page_2.id, keyword_id=keyword_3.id))

        session.commit()

        Assertion(Assertion.EQ)(
            ["keyword1", "keyword2"], [pk.keyword.name for pk in page_1.PageKeywords]
        )
        Assertion(Assertion.EQ)(
            ["keyword1", "keyword3"], [pk.keyword.name for pk in page_2.PageKeywords]
        )

        expected_format_response = {
            "type": "Page",
            "attributes": {
                "text": "text1",
                "id": 1,
                "encrypted_field": "encrypted1",
                "variadic_field": True,
                "variadic_encrypted": 4,
            },
            "include": {
                "PageKeywords": [
                    {
                        "type": "PageKeywords",
                        "attributes": {"page_id": 1, "keyword_id": 1},
                        "include": {
                            "keyword": [
                                {
                                    "type": "Keyword",
                                    "attributes": {"id": 1, "name": "keyword1"},
                                }
                            ]
                        },
                    },
                    {
                        "type": "PageKeywords",
                        "attributes": {"page_id": 1, "keyword_id": 2},
                        "include": {
                            "keyword": [
                                {
                                    "type": "Keyword",
                                    "attributes": {"id": 2, "name": "keyword2"},
                                }
                            ]
                        },
                    },
                ]
            },
        }

        Assertion(Assertion.EQ, diff_split_on=",")(
            page_1.format(include=["PageKeywords", "PageKeywords.keyword"]),
            expected_format_response,
        )

        expected_format_response_2 = {
            "type": "Page",
            "attributes": {
                "text": "text2",
                "id": 2,
                "encrypted_field": "encrypted2",
                "variadic_field": 10.0,
                "variadic_encrypted": [None, None, {"key": []}],
            },
        }

        Assertion(Assertion.EQ, diff_split_on=",")(
            page_2.format(), expected_format_response_2
        )

        # Make sure encryption worked
        should_be_encrypted = orm.engine.execute(
            "SELECT encrypted_field FROM page WHERE id = {0}".format(page_1.id)
        ).fetchone()[0]
        Assertion(Assertion.NEQ)(page_1.encrypted_field, should_be_encrypted)
        if getattr(orm, "cipher", None) is None:
            raise ValueError("ORM cipher not instantiated.")

        Assertion(Assertion.EQ)(
            page_1.encrypted_field,
            orm.cipher.decrypt(should_be_encrypted),  # type: ignore
        )

        expect_exception(PermissionError)(
            lambda: page_1.format(
                include=[
                    "PageKeywords",
                    "PageKeywords.keyword",
                    "PageKeywords.keyword.hidden_relationships",
                ]
            )
        )
        expect_exception(BadRequestError)(
            lambda: page_1.format(include=["a_bad_relationship"])
        )

        expected_format_response["see"] = [  # type: ignore
            dict([(key, item[key]) for key in item if key != "include"])  # type: ignore
            for item in expected_format_response["include"]["PageKeywords"]  # type: ignore
        ]
        del expected_format_response["include"]
        page_1.see(pk_1, pk_2)
        Assertion(Assertion.EQ, diff_split_on=",")(
            page_1.format(), expected_format_response
        )


def main() -> None:
    with DebugUnifiedLoggingContext():
        orm = ORMBuilder("sqlite", base=ORMTestBase)
        orm.migrate()
        test_oop(orm)


if __name__ == "__main__":
    main()
