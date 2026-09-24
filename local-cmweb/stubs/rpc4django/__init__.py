"""Shim standing in for ``rpc4django``."""


def rpcmethod(*_args, **_kwargs):
    """Return a pass-through decorator in place of the real ``@rpcmethod``."""
    def _decorator(func):
        return func
    if len(_args) == 1 and callable(_args[0]) and not _kwargs:
        return _args[0]
    return _decorator
