"""Constants and configuration enums for the DSL module."""

from enum import Enum


class RealEncodingMode(str, Enum):
    """Available encoding strategies for the DSL ``real`` type."""

    REAL = "real"
    FLOATING_POINT = "floating_point"


DEFAULT_REAL_ENCODING = RealEncodingMode.REAL
