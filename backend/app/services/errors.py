"""Application errors independent of HTTP transport."""


class ServiceError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFound(ServiceError):
    pass


class Conflict(ServiceError):
    pass


class InvalidInput(ServiceError):
    pass


class UnsupportedMedia(ServiceError):
    pass


class PayloadTooLarge(ServiceError):
    pass


class PermanentIndexError(Exception):
    """Input or saved job configuration cannot succeed on retry."""
