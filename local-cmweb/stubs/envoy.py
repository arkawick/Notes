"""Shim for ``envoy``.

Faithfully reimplemented over ``subprocess``: envoy is a thin wrapper around
process execution with no service behind it, and ``base/utils/git.py`` depends
on its ``status_code`` / ``std_out`` / ``std_err`` result attributes.
"""

import shlex
import subprocess


class Response(object):
    """Result of a command run."""

    def __init__(self, process=None, std_out='', std_err='', status_code=0,
                 command=''):
        """Store the outcome of the command."""
        self.process = process
        self.std_out = std_out
        self.std_err = std_err
        self.status_code = status_code
        self.command = command

    @property
    def ok(self):
        """Return True if the command exited zero."""
        return self.status_code == 0

    def __repr__(self):
        """Return a debug representation."""
        return '<Response [{}]>'.format(self.status_code)


def run(command, data=None, timeout=None, cwd=None, env=None):
    """Run ``command`` and return a `Response`.

    ``command`` may be a string (split with shlex) or a sequence.
    """
    args = shlex.split(command) if isinstance(command, str) else list(command)
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if data else None, cwd=cwd, env=env)
        out, err = proc.communicate(
            data.encode() if isinstance(data, str) else data, timeout=timeout)
        status = proc.returncode
    except (OSError, ValueError) as exc:
        return Response(std_err=str(exc), status_code=127,
                        command=command)
    except subprocess.TimeoutExpired as exc:
        return Response(std_err=str(exc), status_code=124, command=command)
    decode = lambda b: (b or b'').decode('utf-8', 'replace')  # noqa: E731
    return Response(process=proc, std_out=decode(out), std_err=decode(err),
                    status_code=status, command=command)


def connect(command, data=None, cwd=None, env=None):
    """Alias for `run` -- the streaming variant is not needed locally."""
    return run(command, data=data, cwd=cwd, env=env)
