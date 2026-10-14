# expects the parser saved as emf_text.py
import hashlib
import struct
import unittest

from agents.research.emf_text import extract_emf_text


def rec(t, payload=b''):
  payload = payload + bytes(-len(payload) % 4)
  return struct.pack('<II', t, 8 + len(payload)) + payload


def build(recs, nb=0, nr=0):
  eof = rec(14, struct.pack('<III', 0, 16, 20))
  body = b''.join(recs) + eof
  total = 88 + len(body)
  count = len(recs) + 2
  hp = struct.pack('<4i4i', 0, 0, 100, 100, 0, 0, 1000, 1000)
  hp += struct.pack('<IIIIHHIII', 0x464d4520, 0x10000, total + nb, count + nr, 1, 0, 0, 0, 0)
  hp += struct.pack('<2i2i', 1024, 768, 320, 240)
  return struct.pack('<II', 1, 88) + hp + body


def textw(text='', x=10, y=20, opts=0, dx=None, off_string=None, raw=None,
          rect=(1, 2, 3, 4), t=84):
  s = raw if raw is not None else text.encode('utf-16-le')
  n = len(s) // 2 if t == 84 else len(s)
  base = 76
  offs = base if off_string is None else off_string
  spad = bytes(-len(s) % 4)
  offdx = 0
  dxb = b''
  if dx is not None:
    offdx = base + len(s) + len(spad)
    dxb = struct.pack('<%dI' % len(dx), *dx)
  p = struct.pack('<4i', 0, 0, 0, 0) + struct.pack('<Iff', 1, 1.0, 1.0)
  p += struct.pack('<iiIII', x, y, n, offs, opts) + struct.pack('<4i', *rect)
  p += struct.pack('<I', offdx) + s + spad + dxb
  return rec(t, p)


def small(raw, n, opts, x=5, y=6):
  p = struct.pack('<iiIIIff', x, y, n, opts, 1, 1.0, 1.0)
  if not opts & 0x100:
    p += struct.pack('<4i', 0, 0, 9, 9)
  return rec(108, p + raw)


def font(handle, face='Arial', height=-12, charset=0):
  lf = struct.pack('<5i8B', height, 0, 0, 0, 400, 0, 0, 0, charset, 0, 0, 0, 0)
  lf += face.encode('utf-16-le').ljust(64, bytes(1))
  return rec(82, struct.pack('<I', handle) + lf)


def select(h):
  return rec(37, struct.pack('<I', h))


class EmfTextTests(unittest.TestCase):
  def test_stock_brush_selection_does_not_replace_current_font_and_delete_invalidates_it(self):
    data=build([font(1),select(1),select(0x80000000),textw('literal'),
                rec(40,struct.pack('<I',1)),textw('after deletion')])
    result=extract_emf_text(data)
    self.assertEqual(result['observations'][0]['font']['kind'],'created')
    self.assertEqual(result['observations'][0]['font']['font_record_offset'],88)
    self.assertEqual(result['observations'][1]['font']['kind'],'default_after_delete_unassessed')
    self.assertEqual(result['fonts'][0]['face_name'],'Arial')

  def test_actual_rtl_flag_is_preserved_and_reserved_object_handles_are_rejected(self):
    result=extract_emf_text(build([textw('literal',opts=0x80)]))
    self.assertIn('ETO_RTLREADING',result['observations'][0]['option_flags'])
    for invalid in (select(0),rec(40,struct.pack('<I',0)),rec(40,struct.pack('<I',0x8000000d))):
      with self.assertRaises(ValueError):extract_emf_text(build([invalid]))

  def test_basic_literal_text(self):
    text = ' Hi ' + chr(0xe9) + ' '
    data = build([textw(text, dx=[5, 6, 7, 8, 9, 10], opts=0x4)])
    r = extract_emf_text(data)
    self.assertEqual(r['contract'], 'emf-literal-text-v1')
    self.assertEqual(r['media_sha256'], hashlib.sha256(data).hexdigest())
    o = r['observations'][0]
    self.assertEqual(o['text'], text)
    self.assertEqual(o['record_offset'], 88)
    self.assertEqual(o['record_type'], 84)
    self.assertEqual(o['record_index'], 1)
    self.assertEqual(o['reference'], {'x': 10, 'y': 20})
    self.assertEqual(o['rect'], [1, 2, 3, 4])
    self.assertEqual(o['logical_clip_rect'], [1, 2, 3, 4])
    self.assertEqual(o['string_offset'], 76)
    self.assertEqual(o['spacing']['entries'], [5, 6, 7, 8, 9, 10])
    self.assertEqual(o['raw_hex'], text.encode('utf-16-le').hex())
    self.assertEqual(r['record_counts'], {'1': 1, '14': 1, '84': 1})
    self.assertEqual(o['text_coordinate_system'], 'logical_untransformed')

  def test_pdy(self):
    r = extract_emf_text(build([textw('ab', opts=0x2000, dx=[1, 2, 3, 4])]))
    sp = r['observations'][0]['spacing']
    self.assertEqual(sp['layout'], 'dx_dy_pairs')
    self.assertEqual(sp['entries'], [1, 2, 3, 4])

  def test_poly(self):
    def desc(x, offs, n, offdx=0):
      return struct.pack('<iiIII4iI', x, 0, n, offs, 0, 0, 0, 0, 0, offdx)
    pre = struct.pack('<4i', 0, 0, 0, 0) + struct.pack('<Iff', 1, 1.0, 1.0)
    s1 = 'ab'.encode('utf-16-le')
    s2 = 'c'.encode('utf-16-le') + bytes(2)
    table_end = 40 + 80
    p = pre + struct.pack('<I', 2) + desc(1, table_end, 2) + desc(2, table_end + 4, 1) + s1 + s2
    r = extract_emf_text(build([rec(97, p)]))
    self.assertEqual([o['text'] for o in r['observations']], ['ab', 'c'])
    self.assertEqual([o['string_index'] for o in r['observations']], [0, 1])

  def test_bad_offsets(self):
    for off in (10000, 40, 77):
      with self.assertRaises(ValueError):
        extract_emf_text(build([textw('ab', off_string=off)]))

  def test_bad_dx(self):
    data = bytearray(build([textw('ab', dx=[1, 2])]))
    # offDx lives at record offset 72 -> absolute 88 + 72
    struct.pack_into('<I', data, 88 + 72, 78)
    with self.assertRaises(ValueError):
      extract_emf_text(bytes(data))

  def test_bad_utf16(self):
    with self.assertRaises(ValueError):
      extract_emf_text(build([textw(raw=bytes([0, 0xd8]))]))

  def test_header_counts(self):
    with self.assertRaises(ValueError):
      extract_emf_text(build([textw('a')], nr=1))
    with self.assertRaises(ValueError):
      extract_emf_text(build([textw('a')], nb=4))
    with self.assertRaises(ValueError):
      extract_emf_text(build([textw('a')])[:-4])
    with self.assertRaises(ValueError):
      extract_emf_text(b'')

  def test_record_limit(self):
    recs = [rec(33)] * 100001
    with self.assertRaises(ValueError):
      extract_emf_text(build(recs))

  def test_glyph_index(self):
    r = extract_emf_text(build([textw(raw=bytes([5, 0, 6, 0]), opts=0x10)]))
    o = r['observations'][0]
    self.assertIsNone(o['text'])
    self.assertEqual(o['status'], 'unsupported')
    self.assertEqual(o['raw_hex'], '05000600')
    self.assertEqual(len(r['unsupported']), 1)
    self.assertEqual(r['unsupported'][0]['code'], 'glyph_index_text_unsupported')

  def test_ansi(self):
    r = extract_emf_text(build([textw(raw=b'abc', t=83),
                                textw(raw=bytes([0x41, 0xe9]), t=83)]))
    self.assertEqual(r['observations'][0]['text'], 'abc')
    self.assertIsNone(r['observations'][1]['text'])
    self.assertEqual(r['observations'][1]['raw_hex'], '41e9')
    self.assertEqual(r['unsupported'][0]['code'], 'ansi_non_ascii_unsupported')

  def test_small_text(self):
    r = extract_emf_text(build([small(bytes([0xe9, 0x41]), 2, 0x200 | 0x100),
                                small('hi'.encode('utf-16-le'), 2, 0)]))
    self.assertEqual(r['observations'][0]['text'], chr(0xe9) + 'A')
    self.assertEqual(r['observations'][0]['encoding'], 'small_chars_low_byte_latin1')
    self.assertEqual(r['observations'][1]['text'], 'hi')
    self.assertEqual(r['observations'][1]['rect'], [0, 0, 9, 9])

  def test_font_select_and_handle_reuse(self):
    r = extract_emf_text(build([font(1, 'A'), select(1), textw('x'),
                                font(1, 'B', charset=222), select(1), textw('y')]))
    self.assertEqual(len(r['fonts']), 2)
    f0, f1 = r['fonts']
    self.assertEqual(f0['face_name'], 'A')
    self.assertEqual(f1['face_name'], 'B')
    self.assertEqual(f0['height'], -12)
    self.assertEqual(r['observations'][0]['font']['font_record_offset'], f0['record_offset'])
    self.assertEqual(r['observations'][1]['font']['font_record_offset'], f1['record_offset'])

  def test_unknown_charset_unassessed(self):
    r = extract_emf_text(build([font(1, 'A', charset=99)]))
    self.assertEqual(r['fonts'][0]['charset_status'], 'unassessed')

  def test_save_restore(self):
    r = extract_emf_text(build([font(1, 'A'), font(2, 'B'), select(1), rec(33),
                                select(2), textw('a'), rec(34, struct.pack('<i', -1)),
                                textw('b')]))
    f0, f1 = r['fonts']
    self.assertEqual(r['observations'][0]['font']['font_record_offset'], f1['record_offset'])
    self.assertEqual(r['observations'][1]['font']['font_record_offset'], f0['record_offset'])

  def test_restore_underflow(self):
    with self.assertRaises(ValueError):
      extract_emf_text(build([rec(34, struct.pack('<i', -1))]))

  def test_transform_state_retained_not_applied(self):
    m = struct.pack('<6f', 1.0, 0.0, 0.0, 1.0, 5.0, 6.0)
    r = extract_emf_text(build([rec(17, struct.pack('<I', 8)), rec(35, m), textw('t')]))
    ts = r['observations'][0]['transform_state']
    self.assertEqual(ts['map_mode'], 8)
    self.assertEqual(ts['map_mode_name'], 'MM_ANISOTROPIC')
    self.assertEqual(ts['placement_status'], 'unassessed')
    self.assertEqual(len(r['transform_records']), 1)
    self.assertEqual(r['observations'][0]['reference'], {'x': 10, 'y': 20})

  def test_nonfinite_float_rejected(self):
    with self.assertRaises(ValueError):
      extract_emf_text(build([rec(35, struct.pack('<6f', float('nan'), 0, 0, 1, 0, 0))]))

  def test_emf_plus_comment_unsupported(self):
    d = b'EMF+' + bytes(4)
    r = extract_emf_text(build([rec(70, struct.pack('<I', len(d)) + d)]))
    self.assertEqual(r['unsupported'][0]['code'], 'emf_plus_comment_not_executed')
    self.assertEqual(r['unsupported'][0]['status'], 'unsupported_semantic')


if __name__ == '__main__':
  unittest.main()
