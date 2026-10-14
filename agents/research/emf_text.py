"""Strict native EMF text observations; no rendering or semantic inference.

Generic binary parser code was authored by Claude Code in sanitized session
9309ef3e-b583-40dc-b926-550603d327ce, then reviewed/adapted by Codex.
No private files, names, images, strings or company answers entered that session.
Official layouts: MS-EMF EmrText, EXT/POLY/SMALL text and LogFont records.
https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/dd585d0a-5d7c-4034-963a-1141af836972
https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/20eee81d-0bd4-42d1-a624-860adfe62358
Glyph indices/non-ASCII ANSI remain raw and unsupported, never guessed text.
"""
# module name: emf_text.py
import hashlib
import math
import struct

CONTRACT = 'emf-literal-text-v1'
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 100000
MAX_CHARS_RECORD = 1000000
MAX_TOTAL_UNITS = 2000000
ETO_CLIPPED = 0x4
ETO_GLYPH_INDEX = 0x10
ETO_NO_RECT = 0x100
ETO_SMALL_CHARS = 0x200
ETO_PDY = 0x2000
_OPT_NAMES = ((0x2, 'ETO_OPAQUE'), (0x4, 'ETO_CLIPPED'), (0x10, 'ETO_GLYPH_INDEX'),
              (0x80, 'ETO_RTLREADING'), (0x400, 'ETO_NUMERICSLOCAL'), (0x800, 'ETO_NUMERICSLATIN'),
              (0x100, 'ETO_NO_RECT'), (0x200, 'ETO_SMALL_CHARS'), (0x1000, 'ETO_IGNORELANGUAGE'),
              (0x2000, 'ETO_PDY'))
_CHARSETS = {0, 1, 2, 77, 128, 129, 130, 134, 136, 161, 162, 163, 177, 178, 186, 204, 222, 238, 255}
_MAP_MODES = {1: 'MM_TEXT', 2: 'MM_LOMETRIC', 3: 'MM_HIMETRIC', 4: 'MM_LOENGLISH',
              5: 'MM_HIENGLISH', 6: 'MM_TWIPS', 7: 'MM_ISOTROPIC', 8: 'MM_ANISOTROPIC'}
_MODIFY_MODES = {1: 'MWT_IDENTITY', 2: 'MWT_LEFTMULTIPLY', 3: 'MWT_RIGHTMULTIPLY', 4: 'MWT_SET'}
_OTHER_CREATE = {38, 39, 49, 93, 94, 95, 99, 101}
_REC_NAMES = {83: 'EMR_EXTTEXTOUTA', 84: 'EMR_EXTTEXTOUTW', 96: 'EMR_POLYTEXTOUTA',
              97: 'EMR_POLYTEXTOUTW', 108: 'EMR_SMALLTEXTOUT'}


def _fail(msg):
  raise ValueError(msg)


def _rect(b, o):
  return list(struct.unpack_from('<4i', b, o))


def _u32(b, o):
  return struct.unpack_from('<I', b, o)[0]


def _i32(b, o):
  return struct.unpack_from('<i', b, o)[0]


def _f32(b, o):
  v = struct.unpack_from('<f', b, o)[0]
  if not math.isfinite(v):
    _fail('non-finite float')
  return v


def _walk(data):
  n = len(data)
  off = 0
  recs = []
  while off < n:
    if n - off < 8:
      _fail('truncated record header')
    t, s = struct.unpack_from('<II', data, off)
    if s < 8 or s % 4:
      _fail('bad record size')
    if off + s > n:
      _fail('record exceeds data')
    if not recs and t != 1:
      _fail('first record is not EMR_HEADER')
    if recs and t == 1:
      _fail('duplicate EMR_HEADER')
    recs.append((off, t, s))
    if len(recs) > MAX_RECORDS:
      _fail('too many records')
    off += s
    if t == 14:
      if s < 20:
        _fail('EOF record too small')
      if off != n:
        _fail('data after EOF record')
  if not recs or recs[-1][1] != 14:
    _fail('missing EOF record')
  return recs


def _header(data, records):
  off, t, size = records[0]
  if size < 88:
    _fail('header record too small')
  rec = data[off:off + size]
  if _u32(rec, 40) != 0x464d4520:
    _fail('bad EMF signature')
  if _u32(rec, 48) != len(data):
    _fail('nBytes mismatch')
  if _u32(rec, 52) != len(records):
    _fail('nRecords mismatch')
  n_desc = _u32(rec, 60)
  off_desc = _u32(rec, 64)
  desc = None
  if n_desc:
    if off_desc % 2 or off_desc < 88 or off_desc + 2 * n_desc > size:
      _fail('bad description bounds')
    raw = rec[off_desc:off_desc + 2 * n_desc]
    try:
      text = raw.decode('utf-16-le', 'strict')
    except UnicodeDecodeError:
      _fail('malformed UTF-16LE description')
    desc = {'offset': off_desc, 'n_chars': n_desc, 'raw_hex': raw.hex(), 'text': text}
  return {
      'record_size': size,
      'bounds': _rect(rec, 8),
      'frame': _rect(rec, 24),
      'signature': _u32(rec, 40),
      'version': _u32(rec, 44),
      'n_bytes': _u32(rec, 48),
      'n_records': _u32(rec, 52),
      'handles': struct.unpack_from('<H', rec, 56)[0],
      'n_description': n_desc,
      'off_description': off_desc,
      'description': desc,
      'n_pal_entries': _u32(rec, 68),
      'device': list(struct.unpack_from('<2i', rec, 72)),
      'millimeters': list(struct.unpack_from('<2i', rec, 80)),
  }


def _snapshot(st):
  mm = st['map_mode']
  return {
      'map_mode': mm,
      'map_mode_name': 'unset' if mm is None else _MAP_MODES.get(mm, 'unassessed'),
      'window_ext': st['window_ext'],
      'window_org': st['window_org'],
      'viewport_ext': st['viewport_ext'],
      'viewport_org': st['viewport_org'],
      'world_transform_head_record_offset': st['world_head'],
      'placement_status': 'unassessed',
      'text_coordinate_system': 'logical_untransformed',
  }


def _emit(ctx, base, raw, mode, opts):
  st = ctx['st']
  text = None
  code = None
  if opts & ETO_GLYPH_INDEX:
    encoding = 'raw_glyph_indices'
    code = 'glyph_index_text_unsupported'
  elif mode == 'utf16':
    encoding = 'utf-16-le'
    try:
      text = raw.decode('utf-16-le', 'strict')
    except UnicodeDecodeError:
      _fail('malformed UTF-16LE string')
  elif mode == 'ascii':
    encoding = 'ascii'
    try:
      text = raw.decode('ascii', 'strict')
    except UnicodeDecodeError:
      encoding = 'ansi_raw'
      code = 'ansi_non_ascii_unsupported'
  else:
    encoding = 'small_chars_low_byte_latin1'
    text = raw.decode('latin-1')
  base['raw_hex'] = raw.hex()
  base['encoding'] = encoding
  base['text'] = text
  base['status'] = 'unsupported' if code else 'decoded'
  base['font'] = dict(st['font']) if st['font'] else {'kind': 'none_selected'}
  base['transform_state'] = _snapshot(st)
  base['text_coordinate_system'] = 'logical_untransformed'
  ctx['obs'].append(base)
  if code:
    ctx['uns'].append({
        'code': code,
        'status': 'unsupported',
        'record_offset': base['record_offset'],
        'record_type': base['record_type'],
        'record_index': base['record_index'],
        'string_index': base['string_index'],
        'raw_hex': raw.hex(),
    })


def _flags(opts):
  return [name for bit, name in _OPT_NAMES if opts & bit]


def _text(rec, off, t, idx, ctx):
  wide = t in (84, 97)
  poly = t in (96, 97)
  size = len(rec)
  if size < 36:
    _fail('text record too small')
  bounds = _rect(rec, 8)
  gm = _u32(rec, 24)
  ex = _f32(rec, 28)
  ey = _f32(rec, 32)
  if poly:
    if size < 40:
      _fail('poly text record too small')
    count = _u32(rec, 36)
    pos = 40
    if count * 24 > size:
      _fail('cStrings exceeds record')
  else:
    count = 1
    pos = 36
  descs = []
  for i in range(count):
    if pos + 24 > size:
      _fail('descriptor exceeds record')
    x = _i32(rec, pos)
    y = _i32(rec, pos + 4)
    n = _u32(rec, pos + 8)
    offs = _u32(rec, pos + 12)
    opts = _u32(rec, pos + 16)
    if opts & ETO_NO_RECT:
      rect = None
      dpos = pos + 20
      dsize = 24
    else:
      if pos + 40 > size:
        _fail('descriptor exceeds record')
      rect = _rect(rec, pos + 20)
      dpos = pos + 36
      dsize = 40
    descs.append((i, x, y, n, offs, opts, rect, _u32(rec, dpos)))
    pos += dsize
  table_end = pos
  rec_units = 0
  unit = 2 if wide else 1
  for (i, x, y, n, offs, opts, rect, offdx) in descs:
    if n > MAX_CHARS_RECORD:
      _fail('too many chars in string')
    rec_units += n
    if rec_units > MAX_CHARS_RECORD:
      _fail('too many chars in record')
    ctx['units'] += n
    if ctx['units'] > MAX_TOTAL_UNITS:
      _fail('too many total code units')
    blen = n * unit
    if n or offs:
      if offs < table_end or offs + blen > size:
        _fail('string offset out of bounds')
      if wide and offs % 2:
        _fail('UTF-16 string offset misaligned')
    raw = rec[offs:offs + blen] if blen else b''
    spacing = None
    if offdx:
      pdy = bool(opts & ETO_PDY)
      entries = n * (2 if pdy else 1)
      dlen = entries * 4
      if offdx < table_end or offdx % 4 or offdx + dlen > size:
        _fail('spacing offset invalid')
      if blen and dlen and offs < offdx + dlen and offdx < offs + blen:
        _fail('spacing overlaps string')
      draw = rec[offdx:offdx + dlen]
      spacing = {
          'offset': offdx,
          'length': dlen,
          'layout': 'dx_dy_pairs' if pdy else 'dx',
          'entries': list(struct.unpack_from('<%dI' % entries, rec, offdx)) if entries else [],
          'raw_hex': draw.hex(),
      }
    base = {
        'record_offset': off,
        'record_type': t,
        'record_index': idx,
        'record_name': _REC_NAMES[t],
        'string_index': i if poly else 0,
        'reference': {'x': x, 'y': y},
        'n_chars': n,
        'options': opts,
        'option_flags': _flags(opts),
        'rect': rect,
        'logical_clip_rect': rect if (opts & ETO_CLIPPED and rect is not None) else None,
        'record_bounds': bounds,
        'graphics_mode': gm,
        'ex_scale': ex,
        'ey_scale': ey,
        'string_offset': offs,
        'string_length_bytes': blen,
        'spacing': spacing,
    }
    _emit(ctx, base, raw, 'utf16' if wide else 'ascii', opts)


def _small(rec, off, idx, ctx):
  size = len(rec)
  if size < 36:
    _fail('small text record too small')
  x = _i32(rec, 8)
  y = _i32(rec, 12)
  n = _u32(rec, 16)
  opts = _u32(rec, 20)
  gm = _u32(rec, 24)
  ex = _f32(rec, 28)
  ey = _f32(rec, 32)
  if n > MAX_CHARS_RECORD:
    _fail('too many chars in string')
  ctx['units'] += n
  if ctx['units'] > MAX_TOTAL_UNITS:
    _fail('too many total code units')
  pos = 36
  rect = None
  if not opts & ETO_NO_RECT:
    if pos + 16 > size:
      _fail('small text rect exceeds record')
    rect = _rect(rec, pos)
    pos += 16
  small = bool(opts & ETO_SMALL_CHARS)
  blen = n if small else 2 * n
  if pos + blen > size:
    _fail('small text string exceeds record')
  raw = rec[pos:pos + blen]
  base = {
      'record_offset': off,
      'record_type': 108,
      'record_index': idx,
      'record_name': _REC_NAMES[108],
      'string_index': 0,
      'reference': {'x': x, 'y': y},
      'n_chars': n,
      'options': opts,
      'option_flags': _flags(opts),
      'rect': rect,
      'logical_clip_rect': rect if (opts & ETO_CLIPPED and rect is not None) else None,
      'record_bounds': None,
      'graphics_mode': gm,
      'ex_scale': ex,
      'ey_scale': ey,
      'string_offset': pos,
      'string_length_bytes': blen,
      'spacing': None,
  }
  _emit(ctx, base, raw, 'latin1' if small else 'utf16', opts)


def _font(rec, off, idx):
  if len(rec) < 104:
    _fail('font record too small')
  handle = _u32(rec, 8)
  fn = rec[40:104]
  end = len(fn)
  terminated = False
  for i in range(0, len(fn), 2):
    if fn[i] == 0 and fn[i + 1] == 0:
      end = i
      terminated = True
      break
  try:
    name = fn[:end].decode('utf-16-le', 'strict')
  except UnicodeDecodeError:
    _fail('malformed UTF-16LE face name')
  charset = rec[35]
  return {
      'record_offset': off,
      'record_index': idx,
      'handle': handle,
      'raw_hex': rec[12:].hex(),
      'height': _i32(rec, 12),
      'width': _i32(rec, 16),
      'escapement': _i32(rec, 20),
      'orientation': _i32(rec, 24),
      'weight': _i32(rec, 28),
      'italic': rec[32],
      'underline': rec[33],
      'strike_out': rec[34],
      'charset': charset,
      'charset_status': 'recorded' if charset in _CHARSETS else 'unassessed',
      'out_precision': rec[36],
      'clip_precision': rec[37],
      'quality': rec[38],
      'pitch_and_family': rec[39],
      'face_name': name,
      'face_name_terminated': terminated,
      'face_name_raw_hex': fn.hex(),
  }


def _extract(data):
  if not isinstance(data, (bytes, bytearray, memoryview)):
    _fail('data must be bytes-like')
  data = bytes(data)
  if len(data) > MAX_BYTES:
    _fail('input too large')
  if len(data) < 88:
    _fail('input too small')
  records = _walk(data)
  header = _header(data, records)
  st = {'font': None, 'map_mode': None, 'window_ext': None, 'window_org': None,
        'viewport_ext': None, 'viewport_org': None, 'world_head': None}
  ctx = {'st': st, 'obs': [], 'uns': [], 'units': 0}
  stack = []
  fonts = []
  by_handle = {}
  other = set()
  tr = []
  counts = {}
  for idx, (off, t, size) in enumerate(records):
    rec = data[off:off + size]
    counts[t] = counts.get(t, 0) + 1
    if t in (83, 84, 96, 97):
      _text(rec, off, t, idx, ctx)
    elif t == 108:
      _small(rec, off, idx, ctx)
    elif t == 82:
      f = _font(rec, off, idx)
      fonts.append(f)
      by_handle[f['handle']] = off
      other.discard(f['handle'])
    elif t in _OTHER_CREATE:
      if size < 12:
        _fail('create record too small')
      h = _u32(rec, 8)
      other.add(h)
      by_handle.pop(h, None)
    elif t == 37:
      if size < 12:
        _fail('select record too small')
      h = _u32(rec, 8)
      if h == 0:
        _fail('reserved select object handle')
      if h & 0x80000000:
        if h in {0x8000000a,0x8000000b,0x8000000c,0x8000000d,0x8000000e,0x80000010,0x80000011}:
          st['font'] = {'kind': 'stock', 'handle': h}
      elif h in by_handle:
        st['font'] = {'kind': 'created', 'handle': h, 'font_record_offset': by_handle[h]}
      elif h in other:
        pass
      else:
        st['font'] = {'kind': 'unresolved', 'handle': h}
        ctx['uns'].append({'code': 'select_object_unresolved_handle', 'status': 'unassessed',
                           'record_offset': off, 'record_type': t, 'record_index': idx,
                           'handle': h})
    elif t == 40:
      if size < 12:
        _fail('delete record too small')
      h = _u32(rec, 8)
      if h == 0 or h & 0x80000000:
        _fail('reserved or stock delete object handle')
      by_handle.pop(h, None)
      other.discard(h)
      if st['font'] and st['font'].get('handle') == h:
        st['font'] = {'kind':'default_after_delete_unassessed','delete_record_offset':off}
    elif t == 33:
      stack.append(dict(st))
    elif t == 34:
      if size < 12:
        _fail('restore record too small')
      rel = _i32(rec, 8)
      if rel >= 0 or -rel > len(stack):
        _fail('invalid RestoreDC')
      saved = None
      for _ in range(-rel):
        saved = stack.pop()
      st.clear()
      st.update(saved)
    elif t == 17:
      if size < 12:
        _fail('map mode record too small')
      st['map_mode'] = _u32(rec, 8)
    elif t in (9, 10, 11, 12):
      if size < 16:
        _fail('extent/origin record too small')
      key = {9: 'window_ext', 10: 'window_org', 11: 'viewport_ext', 12: 'viewport_org'}[t]
      st[key] = [_i32(rec, 8), _i32(rec, 12)]
    elif t == 35:
      if size < 32:
        _fail('world transform record too small')
      m = [_f32(rec, 8 + 4 * k) for k in range(6)]
      tr.append({'record_offset': off, 'record_index': idx, 'record_type': t,
                 'op': 'SETWORLDTRANSFORM', 'matrix': m, 'mode': None, 'mode_name': None,
                 'previous_record_offset': st['world_head'], 'applied': False})
      st['world_head'] = off
    elif t == 36:
      if size < 36:
        _fail('modify world transform record too small')
      m = [_f32(rec, 8 + 4 * k) for k in range(6)]
      mode = _u32(rec, 32)
      tr.append({'record_offset': off, 'record_index': idx, 'record_type': t,
                 'op': 'MODIFYWORLDTRANSFORM', 'matrix': m, 'mode': mode,
                 'mode_name': _MODIFY_MODES.get(mode, 'unassessed'),
                 'previous_record_offset': st['world_head'], 'applied': False})
      st['world_head'] = off
    elif t == 70:
      if size < 12:
        _fail('comment record too small')
      dsz = _u32(rec, 8)
      if 12 + dsz > size:
        _fail('comment data exceeds record')
      if dsz >= 4 and rec[12:16] == b'EMF+':
        ctx['uns'].append({'code': 'emf_plus_comment_not_executed',
                           'status': 'unsupported_semantic',
                           'record_offset': off, 'record_type': t, 'record_index': idx,
                           'data_size': dsz,
                           'raw_sha256': hashlib.sha256(rec[12:12 + dsz]).hexdigest()})
  return {
      'contract': CONTRACT,
      'media_sha256': hashlib.sha256(data).hexdigest(),
      'header': header,
      'fonts': fonts,
      'observations': ctx['obs'],
      'unsupported': ctx['uns'],
      'record_counts': {str(k): counts[k] for k in sorted(counts)},
      'transform_records': tr,
  }


def extract_emf_text(data):
  try:
    return _extract(data)
  except struct.error as e:
    raise ValueError('truncated structure: %s' % e)
