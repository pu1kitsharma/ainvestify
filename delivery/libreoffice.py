"""Isolated LibreOffice CLI round trips; explicit UNO remains separately qualified."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

from delivery.inspection import inspect_bytes
from delivery.isolation import private_temp_root,run_private


MAC_BINARY='/Applications/LibreOffice.app/Contents/MacOS/soffice'
LINUX_CANDIDATES=('/usr/bin/soffice','/usr/local/bin/soffice','/usr/lib/libreoffice/program/soffice',
    '/opt/libreoffice/program/soffice','/snap/bin/libreoffice')


def find_binary(*,environ=None,system=None,which=None):
    """LIBREOFFICE_BINARY first (any OS); then macOS app path, or on Linux `soffice`/`libreoffice` on PATH
    and common install locations. Returns a Path to an existing file, or None. Nothing is started."""
    import platform,shutil
    environ=os.environ if environ is None else environ
    system=system or platform.system()
    which=which or shutil.which
    explicit=environ.get('LIBREOFFICE_BINARY')
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    if system=='Darwin':
        return Path(MAC_BINARY) if Path(MAC_BINARY).is_file() else None
    if system=='Linux':
        for name in ('soffice','libreoffice'):
            found=which(name)
            if found and Path(found).is_file():return Path(found)
        for candidate in LINUX_CANDIDATES:
            if Path(candidate).is_file():return Path(candidate)
    return None


def office_read_roots(binary,*,system=None):
    """Immutable install tree the sandboxed office process may read.
    macOS: the .app bundle (…/X.app). Linux: the resolved install dir (parent of `program/`)."""
    import platform
    system=system or platform.system()
    if system=='Linux':
        resolved=Path(binary).resolve()
        return (resolved.parent.parent,)
    return (Path(binary).parents[2],)


def sandbox_binary(binary,*,system=None):
    """Path handed to the sandbox: resolved on Linux so symlinks into the install tree stay readable."""
    import platform
    return Path(binary).resolve() if (system or platform.system())=='Linux' else Path(binary)


def office_binary():
    binary=find_binary()
    if binary is None:raise RuntimeError('libreoffice_unavailable')
    return binary


def convert(content,source_format,target_format,*,timeout=90):
    if source_format not in {'xlsx','pptx','docx'} or target_format not in {'pdf','xlsx'}:
        raise ValueError('Unsupported conversion')
    if target_format=='xlsx' and source_format!='xlsx':raise ValueError('Workbook round trip requires XLSX')
    inspection=inspect_bytes(content,source_format)
    allowed={'missing_formula_cache','stored_cell_error','broken_formula_reference','broken_defined_name',
        'embedded_payload_requires_audience_review'}
    if any(f['code'] not in allowed for f in inspection['findings']):
        raise ValueError('Unsupported active/external or malformed document')
    binary=sandbox_binary(office_binary())
    # macOS's per-user TMPDIR can exceed sockaddr_un once LibreOffice adds
    # its OSL_PIPE name. Keep the private (0700) job at a short local path.
    with tempfile.TemporaryDirectory(prefix='private-office-',dir=private_temp_root()) as directory:
        job=Path(directory).resolve();source=job/f'input.{source_format}';source.write_bytes(content)
        profile=job/'profile';(profile/'user').mkdir(parents=True)
        # Disable macros and automatic external-link updates for every new profile.
        (profile/'user/registrymodifications.xcu').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
</oor:items>''')
        output=job/'output';output.mkdir()
        # LibreOffice otherwise binds its single-instance OSL_PIPE socket in
        # /tmp.  The private worker permits Unix IPC only inside this job.
        # When /tmp is not writable, LibreOffice uses this bootstrap path.
        args=[binary,f'-env:UserInstallation={profile.as_uri()}',
            f'-env:OSL_SOCKET_PATH={job}','--headless','--nologo','--nodefault','--norestore',
            '--convert-to',target_format,'--outdir',output,source]
        run_private(args,job,timeout=timeout,extra_read=office_read_roots(binary),local_ipc=True)
        target=output/f'input.{target_format}'
        if not target.is_file():raise RuntimeError('libreoffice_produced_no_output')
        result=target.read_bytes()
        # A successful process is not a passing calculation/layout verdict.
        return result
