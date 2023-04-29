class EmptyFileError(Exception):
    """
    An exception thrown when an imported file has no rows. Useful for spreadsheet imports.

    :param path str: The file that is empty.
    """

    def __init__(self, path: str):
        super(EmptyFileError, self).__init__("No rows in file at {0}".format(path))
