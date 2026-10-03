"""Scoped immutable byte storage using no-follow directory-relative file access."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import os
import re
import stat
from pathlib import Path

MAX_FILE_BYTES = 32 * 1024 * 1024


def read_source_bytes(path):
    """Read the checked regular-file inode, never a later path replacement."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
            raise ValueError("Unsupported source file")
        content = stream.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Source file outside supported limits")
    return content


def scope_component(value):
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def scoped_directory(root,tenant,room,*,create=False):
    root=Path(root)
    if root.is_symlink():raise ValueError('Symlink storage root is not permitted')
    if create:root.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(str(root),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in (scope_component(tenant),scope_component(room)):
            if create:
                try:os.mkdir(part,mode=0o700,dir_fd=fd)
                except FileExistsError:pass
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        yield fd
    finally:os.close(fd)


def _read(directory,digest):
    fd=os.open(digest,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
    with os.fdopen(fd,'rb') as stream:content=stream.read(MAX_FILE_BYTES+1)
    if len(content)>MAX_FILE_BYTES or hashlib.sha256(content).hexdigest()!=digest:
        raise ValueError('Artifact bytes no longer match the approved hash')
    return content


def store_bytes(root,tenant,room,content):
    if not content or len(content)>MAX_FILE_BYTES:raise ValueError('Artifact size outside supported limits')
    digest=hashlib.sha256(content).hexdigest()
    with scoped_directory(root,tenant,room,create=True) as directory:
        try:fd=os.open(digest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        except FileExistsError:
            if _read(directory,digest)!=content:raise ValueError('Content-address collision')
        else:
            with os.fdopen(fd,'wb') as stream:
                stream.write(content);stream.flush();os.fsync(stream.fileno())
    return digest


def read_bytes(root,tenant,room,digest):
    if not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('Invalid content identifier')
    with scoped_directory(root,tenant,room) as directory:return _read(directory,digest)
