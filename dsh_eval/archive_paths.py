"""Explicit, read-only relocation of listed archive paths without changing saved bytes."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType


_ACTIVE = ContextVar("dsh_archive_read_paths", default=None)
_BLOCKED = {"home", "workspace", "node_modules", "private-notes", "secrets", "credentials", "__pycache__"}
_CLAIM = ".batch-resume-claim.json"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _member(value):
    _require(isinstance(value, str) and bool(value.strip()) and "\\" not in value and ":" not in value
             and not any(ord(char) < 32 for char in value), "Invalid archive member path")
    parts = value.split("/")
    _require(all(part not in ("", ".", "..") and part.casefold() not in _BLOCKED
                 and (not part.startswith(".") or index == len(parts) - 1 and part == _CLAIM)
                 for index, part in enumerate(parts)), "Archive member path is not allowed")
    return value


def _text(value):
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise ValueError("Archive reference must be a path") from error
    _require(isinstance(text, str) and bool(text) and not any(ord(char) < 32 for char in text),
             "Invalid archive reference")
    return text


def _is_link(path):
    return path.is_symlink() or path.is_junction()


@dataclass(frozen=True, init=False)
class ArchivePaths:
    """Translate one original absolute prefix to an immutable, listed payload tree."""

    logical_source_root: str
    payload_root: Path
    members: frozenset
    _origin: object
    _windows: bool
    _files: object
    _directories: object

    def __init__(self, logical_source_root, payload_root, members):
        raw = _text(logical_source_root)
        windows = PureWindowsPath(raw).is_absolute()
        origin = PureWindowsPath(raw) if windows else PurePosixPath(raw)
        _require(origin.is_absolute() and ".." not in origin.parts, "Archive logical root must be absolute")
        payload = Path(payload_root)
        _require(payload.is_absolute(), "Archive payload root must be absolute")
        _require(not _is_link(payload), "Archive payload cannot be a link")
        payload = payload.resolve()
        _require(payload.is_dir(), "Archive payload root is missing")
        _require(not isinstance(members, (str, bytes)), "Archive members must be a collection")
        key = str.casefold if windows else lambda value: value
        files, directories = {}, {"": ""}
        try:
            for value in members:
                name = _member(value)
                _require(key(name) not in files, "Duplicate archive member")
                files[key(name)] = name
                for parent in PurePosixPath(name).parents:
                    directory = "" if str(parent) == "." else parent.as_posix()
                    old = directories.setdefault(key(directory), directory)
                    _require(old == directory, "Archive directory spelling is ambiguous")
        except TypeError as error:
            raise ValueError("Archive members must be a collection of paths") from error
        _require(bool(files) and not files.keys() & directories.keys(), "Archive members are empty or collide with directories")
        # A POSIX archive cannot use distinct spellings that alias on the current Windows filesystem.
        if os.name == "nt":
            names = list(files.values()) + list(directories.values())
            _require(len({name.casefold() for name in names}) == len(names), "Archive member spellings collide on Windows")
        object.__setattr__(self, "logical_source_root", str(origin))
        object.__setattr__(self, "payload_root", payload)
        object.__setattr__(self, "members", frozenset(files.values()))
        object.__setattr__(self, "_origin", origin)
        object.__setattr__(self, "_windows", windows)
        object.__setattr__(self, "_files", MappingProxyType(files))
        object.__setattr__(self, "_directories", MappingProxyType(directories))

    def _relative(self, value):
        raw = _text(value)
        # Parse logical paths without resolving or probing their original filesystem.
        origin = type(self._origin)(raw)
        logical = origin.relative_to(self._origin) if origin.is_absolute() and origin.is_relative_to(self._origin) else None
        physical = Path(raw)
        if physical.is_absolute() and physical.is_relative_to(self.payload_root):
            return physical.relative_to(self.payload_root).as_posix()
        return logical.as_posix() if logical is not None else None

    def recognizes(self, value):
        """Recognize owned prefixes even when their referenced member is unlisted."""
        try:
            return self._relative(value) is not None
        except ValueError:
            return False

    def _listed(self, value):
        relative = self._relative(value)
        _require(relative is not None, "Archive reference is outside the declared prefixes")
        relative = "" if relative == "." else relative
        _require(".." not in PurePosixPath(relative).parts, "Archive reference contains parent traversal")
        key = relative.casefold() if self._windows else relative
        canonical = self._files.get(key, self._directories.get(key))
        _require(canonical is not None, "Archive reference is not a listed member or directory")
        return canonical

    def physical(self, value):
        relative = self._listed(value)
        target = self.payload_root
        _require(not _is_link(target), "Archive payload became a link")
        for part in PurePosixPath(relative).parts:
            target = target / part
            _require(not _is_link(target), "Archive reference contains a link")
        resolved = target.resolve()
        _require(resolved.is_relative_to(self.payload_root), "Archive reference escaped the payload")
        return resolved

    def logical_str(self, value):
        relative = self._listed(value)
        return str(self._origin.joinpath(*PurePosixPath(relative).parts))


def archive_context_active():
    return _ACTIVE.get() is not None


def physical(value):
    resolver = _ACTIVE.get()
    return resolver.physical(value) if resolver is not None else Path(value).resolve()


def logical_str(value):
    resolver = _ACTIVE.get()
    return resolver.logical_str(value) if resolver is not None else str(value)


@contextmanager
def archive_read_context(resolver):
    _require(isinstance(resolver, ArchivePaths), "Invalid archive path resolver")
    current = _ACTIVE.get()
    _require(current is None or current is resolver, "Cannot nest different archive path mappings")
    token = _ACTIVE.set(resolver)
    try:
        yield resolver
    finally:
        _ACTIVE.reset(token)
