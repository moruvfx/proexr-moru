class ProexrError(Exception):
    pass


class UnsupportedMediaError(ProexrError):
    pass


class MediaReadError(ProexrError):
    pass


class ColorConfigError(ProexrError):
    pass


class PlaylistError(ProexrError):
    """A playlist file could not be read or written."""


class UpdateError(ProexrError):
    """Checking for or downloading an update failed."""
