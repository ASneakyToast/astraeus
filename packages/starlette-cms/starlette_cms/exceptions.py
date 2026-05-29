class CMSSchemaMismatch(Exception):
    """Raised on startup when the database schema version doesn't match the package version."""


class BlockNotFound(Exception):
    """Raised when a block type name is not found in the registry."""


class BlockRegistrationError(Exception):
    """Raised when a block type name collision occurs during registration."""
