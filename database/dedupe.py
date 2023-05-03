import os
import sys

try:
    import dedupe
except ImportError:
    sys.stderr.write(f"Dedupe package missing. Run `pip install dedupe` to get it.\r\n")
    sys.stderr.flush()
    raise

import sqlalchemy

from typing import Any, List, Dict
from statistics import median
from pibble.util.log import logger
from pibble.database.engine import EngineFactory
from pibble.database.util import row_to_dict

from sqlalchemy.sql.type_api import TypeEngine as SQLAlchemyType


class DeDuplicator:
    """
    A class that helps with de-duplication of data.

    This will load all data into memory, so should be used on reasonably-sized data sets. Uses the python ``dedupe`` module,
    which is a machine learning algorithm. Put simply, you configure relevant fields to look at, then the module will
    ascertain the average difference between these fields using various methods (n-gram text analysis, levenshtein edit distance,
    etc.). Based upon the difference, a weight is assigned and a summed value of each row is compared to one another. If the summed
    value is close enough, it is marked as a possible duplicate using a value from 0 to 1. 0 is the least likely (though still possible), and 1 is the most likely (almost assuredly). No value represents no likeliness it is a duplicate.
    """

    STEP_SIZE = 30000

    def __init__(
        self,
        database_type: str,
        database_params: Dict[str, Any],
        tablename: str,
        unique_key: str,
        unique_key_type: SQLAlchemyType,
        fields: List[str],
    ) -> None:
        self.settings_file = os.path.join(os.getcwd(), "{0}.settings".format(tablename))
        self.training_file = os.path.join(os.getcwd(), "{0}.training".format(tablename))

        self.database_type = database_type
        self.database_params = database_params
        self.tablename = tablename
        self.unique_key = unique_key
        self.unique_key_type = unique_key_type

        self.factory = EngineFactory(**{database_type: database_params})
        self.fields = fields

    def run(self) -> None:
        """
        Runs the deduplicator to completion.
        """
        self.gather()
        self.train()
        self.cluster()

    def sample(self, row: Any) -> Dict[str, Any]:
        """
        A helper method to turn a row into a "sample", expected by dedupe.

        Notably this turns it into a dictionary, and turns empty strings into "None".
        """
        row_dict = row_to_dict(row)
        return dict(
            [
                (
                    key,
                    row_dict[key]
                    if not (isinstance(row_dict[key], str) and len(row_dict[key]) == 0)
                    else None,
                )
                for key in row_dict
            ]
        )

    def gather(self) -> None:
        """
        Gathers data from the deduplicator configuration.
        """
        logger.info("Creating connection engines.")
        with self.factory as factory:
            engine = next(iter(factory[self.database_type]))
            meta = sqlalchemy.MetaData(engine)
            table = sqlalchemy.Table(
                self.tablename, meta, autoload=True, autoload_with=engine
            )

            logger.info("Source table introspected, gathering data.")
            self.data = dict(
                [
                    (i, self.sample(row))
                    for i, row in enumerate(engine.execute(table.select()).fetchall())
                ]
            )

    def train(self) -> None:
        """
        Trains against gathered data
        """
        if os.path.exists(self.settings_file):
            logger.info("Loading training data from {0}".format(self.settings_file))
            with open(self.settings_file, "rb") as fp:
                self.deduper = dedupe.StaticDedupe(fp)
        else:
            logger.info("Starting training.")
            self.deduper = dedupe.Dedupe(self.fields)

            logger.info("Sampling data.")
            self.deduper.sample(self.data)

            if os.path.exists(self.training_file):
                logger.info(
                    "Reading training examples from {0}".format(self.training_file)
                )
                with open(self.training_file, "rb") as fp:
                    self.deduper.readTraining(fp)

            logger.info("Training against data.")

            dedupe.convenience.consoleLabel(self.deduper)
            self.deduper.train()

            with open(self.training_file, "w") as fp:
                self.deduper.writeTraining(fp)

            with open(self.settings_file, "wb") as fp:
                self.deduper.writeSettings(fp)

    def cluster(self) -> None:
        logger.info("Clustering data.")
        self.threshold = self.deduper.threshold(self.data, recall_weight=1)
        self.clustered_duplicates = self.deduper.match(self.data, self.threshold)

        logger.info(
            "{0:d} clustered duplicate sets found. Writing cluster table.".format(
                len(self.clustered_duplicates)
            )
        )

        with self.factory as factory:
            engine = next(iter(factory[self.database_type]))
            meta = sqlalchemy.MetaData(engine)
            try:
                table = sqlalchemy.Table(
                    "{0}_clustered_sets".format(self.tablename),
                    meta,
                    autoload=True,
                    autoload_with=engine,
                )
                table.drop(engine)
                meta = sqlalchemy.MetaData(engine)
            except sqlalchemy.exc.NoSuchTableError:
                pass

            source_table = sqlalchemy.Table(
                self.tablename, meta, autoload=True, autoload_with=engine
            )

            table = sqlalchemy.Table(
                "{0}_clustered_sets".format(self.tablename),
                meta,
                sqlalchemy.Column(
                    "cluster_entry_id",
                    sqlalchemy.Integer,
                    sqlalchemy.Sequence("cluster_entry_id_sequence", metadata=meta),
                    primary_key=True,
                ),
                sqlalchemy.Column("cluster_id", sqlalchemy.Integer, index=True),
                sqlalchemy.Column(
                    self.unique_key,
                    self.unique_key_type,
                    sqlalchemy.ForeignKey(
                        getattr(source_table.c, self.unique_key),
                        ondelete="CASCADE",
                        onupdate="CASCADE",
                    ),
                ),
                sqlalchemy.Column("score", sqlalchemy.Float),
            )

            meta.create_all()

            for min_int in range(10):
                minimum = min_int / 10
                logger.info(
                    "Duplicates with likeliness above threshold {0:0.2f}: {1:d}".format(
                        minimum,
                        len(
                            [
                                cluster
                                for cluster in self.clustered_duplicates
                                if median(cluster[1]) >= minimum
                            ]
                        ),
                    )
                )

            for i, cluster in enumerate(self.clustered_duplicates):
                engine.execute(
                    table.insert(),
                    [
                        {
                            self.unique_key: self.data[uid][self.unique_key],
                            "score": float(score),
                            "cluster_id": i,
                        }
                        for uid, score in zip(cluster[0], cluster[1])
                    ],
                )

        logger.info("Clustering complete.")
