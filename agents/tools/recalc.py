"""Isolated LibreOffice recalculation compared with the pure-Python evaluator.

Fail closed: when the macOS private-process boundary or LibreOffice is unavailable
the result is an explicit mandatory UNRUN, never a pass. Work happens on a copy in
a temporary 0700 job directory with a fresh profile, macros and link updates off,
no network (Seatbelt denies it), a timeout and an output-size bound. Nothing here
writes into the caller's workbook or qualifies Office behaviour.
"""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import platform
import re
import tempfile

from openpyxl import load_workbook

from .contracts import bounded_package
from .formula_engine import (XlErr, a1, compare_with_cache, evaluate_model, load_model, values_equal, _is_num)

_ALLOWED_FINDINGS = {'missing_formula_cache', 'stored_cell_error', 'broken_formula_reference', 'broken_defined_name',
                     'embedded_payload_requires_audience_review'}
_PROFILE = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>'''


_EXTERNAL = re.compile(r"(?i)\[\d+\]|'?\[[^\]]*\.(?:xls[xmb]?|xlam)\]|://|\|'|\b(?:WEBSERVICE|HYPERLINK|RTD|DDE|CALL|REGISTER\.ID)\s*\(")


def _external_reference(text):
    """External-workbook, URL, DDE or network-function formulas (table structured refs like T[Col] are fine)."""
    return _EXTERNAL.search(text) is not None


def unrun(reason, **extra):
    return {'status': 'UNRUN', 'mandatory_unrun': True, 'reason': reason, 'passed': False,
            'office_recalculation': 'not_performed', **extra}


def availability():
    """Return (available: bool, reason). Nothing is started. Seatbelt on macOS, bubblewrap on Linux;
    anything else (or no LibreOffice) is UNRUN, never an unsandboxed run."""
    from delivery.isolation import isolation_available
    from delivery.libreoffice import find_binary
    ok, reason = isolation_available()
    if not ok:
        return False, reason
    if find_binary() is None:
        return False, 'libreoffice_unavailable'
    return True, 'available'


def strip_caches(content):
    """Re-save formulas without stored results so every value must be recalculated."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        book = load_workbook(BytesIO(content), data_only=False, keep_links=False)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def recalculate_with_libreoffice(content, *, timeout=90, max_input_bytes=20_000_000, max_output_bytes=40_000_000,
                                 max_cells=200_000, allow_finding_codes=()):
    """Return {'status':'recalculated','content':bytes} or an UNRUN/failed record (never raises for environment)."""
    ok, reason = availability()
    if not ok:
        return unrun(reason)
    try:
        if len(content) > max_input_bytes:
            return {'status': 'failed', 'passed': False, 'reason': 'input_exceeds_byte_budget'}
        bounded_package(content, max_bytes=max_input_bytes, max_cells=max_cells)
        from delivery.inspection import inspect_bytes
        findings = inspect_bytes(content, 'xlsx')['findings']
        allowed = _ALLOWED_FINDINGS | set(allow_finding_codes)   # explicit Python-API opt-in only; not exposed to agents
        if any(f['code'] not in allowed for f in findings):
            return {'status': 'failed', 'passed': False, 'reason': 'unsupported_active_or_external_content',
                    'finding_codes': sorted({f['code'] for f in findings} - allowed)}
        model = load_model(content, max_bytes=max_input_bytes, max_cells=max_cells)
        external = [f'{sd.name}!{a1(r, c)}' for sd in model.sheets.values() for (r, c), text in sd.formulas.items() if _external_reference(text)]
        if external:
            return {'status': 'failed', 'passed': False, 'reason': 'external_or_network_formula', 'cells': external[:20]}
        stripped = strip_caches(content)
        from delivery.isolation import run_private
        from delivery.isolation import private_temp_root
        from delivery.libreoffice import find_binary, office_read_roots, sandbox_binary
        found = find_binary()
        if found is None:
            return unrun('libreoffice_unavailable')
        binary = sandbox_binary(found)
        # Short private path: LibreOffice's pipe name must fit sockaddr_un on macOS.
        with tempfile.TemporaryDirectory(prefix='private-recalc-', dir=private_temp_root()) as directory:
            job = Path(directory).resolve()
            os.chmod(job, 0o700)
            source = job / 'input.xlsx'
            source.write_bytes(stripped)
            profile = job / 'profile'
            (profile / 'user').mkdir(parents=True)
            (profile / 'user/registrymodifications.xcu').write_text(_PROFILE)
            output = job / 'output'
            output.mkdir()
            args = [binary, f'-env:UserInstallation={profile.as_uri()}', f'-env:OSL_SOCKET_PATH={job}', '--headless', '--nologo',
                    '--nodefault', '--norestore', '--convert-to', 'xlsx', '--outdir', output, source]
            run_private(args, job, timeout=timeout, extra_read=office_read_roots(binary), local_ipc=True)
            target = output / 'input.xlsx'
            if not target.is_file():
                return {'status': 'failed', 'passed': False, 'reason': 'libreoffice_produced_no_output'}
            size = target.stat().st_size
            if size > max_output_bytes:
                return {'status': 'failed', 'passed': False, 'reason': 'output_exceeds_byte_budget', 'output_bytes': size}
            return {'status': 'recalculated', 'content': target.read_bytes(), 'output_bytes': size}
    except TimeoutError:
        return {'status': 'failed', 'passed': False, 'reason': 'libreoffice_timeout', 'timeout_seconds': timeout}
    except RuntimeError as exc:
        text = str(exc)
        if text == 'private_process_isolation_unavailable':
            return unrun(text)
        return {'status': 'failed', 'passed': False, 'reason': text}
    except Exception as exc:                                    # malformed package etc.
        return {'status': 'failed', 'passed': False, 'reason': f'{type(exc).__name__}: {exc}'}


def compare_libreoffice_to_engine(content, *, timeout=90, rel_tol=1e-9, abs_tol=1e-9, max_listed=50, **limits):
    """Recalculate in LibreOffice and compare every formula cell with the Python evaluator."""
    model = load_model(content, max_bytes=limits.get('max_input_bytes', 20_000_000), max_cells=limits.get('max_cells', 200_000))
    engine = evaluate_model(model)
    run = recalculate_with_libreoffice(content, timeout=timeout, **limits)
    if run['status'] != 'recalculated':
        return {**{k: v for k, v in run.items() if k != 'content'}, 'engine_formula_cells': len(engine.values)}
    lo_model = load_model(run['content'], max_bytes=max(limits.get('max_input_bytes', 20_000_000), len(run['content']) + 1),
                          max_cells=limits.get('max_cells', 200_000))
    compared = matches = 0
    lo_errors, mismatches, blocked = [], [], []
    for key, mine in engine.values.items():
        sd = lo_model.sheets.get(key[0])
        lo = sd.cached.get((key[1], key[2])) if sd else None
        label = engine.label(key)
        if isinstance(lo, XlErr):
            lo_errors.append({'cell': label, 'libreoffice': lo.code})
        if isinstance(mine, XlErr) and mine.code in ('#UNSUPPORTED!',):
            blocked.append(label)
            continue
        compared += 1
        # LibreOffice reports an empty-string result as blank; treat blank and '' alike.
        if values_equal(mine, lo, rel_tol, abs_tol) or (mine == '' and lo is None):
            matches += 1
        elif len(mismatches) < max_listed:
            mismatches.append({'cell': label, 'engine': mine.code if isinstance(mine, XlErr) else mine,
                               'libreoffice': lo.code if isinstance(lo, XlErr) else lo,
                               'formula': model.sheets[key[0]].formulas[(key[1], key[2])][:140]})
    mismatch_total = compared - matches
    stored = compare_with_cache(engine, rel=rel_tol, abs_tol=abs_tol, max_listed=0)
    return {'status': 'compared', 'passed': mismatch_total == 0, 'mandatory_unrun': False,
            'office_recalculation': 'libreoffice_headless_isolated_copy', 'compared_cells': compared, 'matching_cells': matches,
            'mismatch_count': mismatch_total, 'agreement': (matches / compared) if compared else None,
            'mismatches': mismatches, 'libreoffice_error_cells': lo_errors[:max_listed], 'libreoffice_error_count': len(lo_errors),
            'engine_blocked_by_unsupported': blocked[:max_listed],
            'engine_vs_stored_cache_numeric_match_rate': stored['numeric_match_rate'],
            'output_bytes': run['output_bytes'],
            'note': 'LibreOffice agreement is evidence of engine parity, not Excel qualification or financial acceptance'}
