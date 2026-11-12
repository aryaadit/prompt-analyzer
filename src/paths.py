"""Path helpers that treat Mac and Windows paths correctly, whichever machine they are read on.

A session log written on Windows holds paths like C:\\Users\\Anna\\runs\\task-1. Python's own
os.path only understands the paths of the machine it runs on, so these helpers pick the right
rules from the path itself. Pure string work: nothing here touches the disk.
"""
import ntpath
import posixpath
import re

_WINDOWS_START = re.compile(r'^(?:[A-Za-z]:[\\/]|\\\\)')  # C:\ or C:/ or a network share


def is_windows_path(path):
    """True when the path starts like a Windows path (a drive letter or a network share)."""
    return isinstance(path, str) and bool(_WINDOWS_START.match(path))


def flavor(path):
    """The path module that matches this path: ntpath for Windows paths, posixpath otherwise."""
    return ntpath if is_windows_path(path) else posixpath


def basename(path):
    """The last part of a folder path, ignoring a trailing slash. Empty string for nothing."""
    path = (path or '').rstrip('/\\')
    return flavor(path).basename(path) if path else ''


def relative_under(path, base):
    """Return path relative to base when it sits inside base, else None. Case-blind on Windows."""
    if not path or not base:
        return None
    mod = flavor(base)
    if mod is ntpath:
        norm_path, norm_base = ntpath.normpath(path), ntpath.normpath(base).rstrip('\\')
        if ntpath.normcase(norm_path).startswith(ntpath.normcase(norm_base) + '\\'):
            return norm_path[len(norm_base) + 1:]
        return None
    base = base.rstrip('/')
    return posixpath.relpath(path, base) if path.startswith(base + '/') else None


def path_key(path, cwd):
    """One normalized key per file: absolute, with a relative path resolved against cwd."""
    if not path:
        return None
    mod = flavor(cwd or path)
    if path.startswith('~') or mod.isabs(path) or not cwd:
        return mod.normpath(path)
    return mod.normpath(mod.join(cwd, path))
