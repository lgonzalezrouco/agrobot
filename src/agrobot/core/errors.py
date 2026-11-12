class NotFoundError(Exception):
    """A requested entity does not exist."""


class ConflictError(Exception):
    """The change clashes with existing state (e.g. a unique value already taken)."""
