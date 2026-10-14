"""Independent glyph/clip/cache boundary; one fictional binary source.

Numbers that exist only as glyph indexes must not become financial literals.
These synthetic assertions are software checks, not company answers or gold.
"""
from io import BytesIO
from zipfile import ZipFile

from agents.research import document_evidence_manifest as dm
from agents.research import document_generation as dg
from agents.research import document_literal_catalog as lc
from tests.research.test_document_native_visual_text import IDENTITY, source_bytes
from tests.research.test_emf_text import build, font, select, textw


def test_glyph_digits_never_become_quoteable_and_clip_cache_scope_is_retained():
    with ZipFile(BytesIO(source_bytes())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    glyph_looking_digits = '3002'
    stored_clipped_literal = ' Whole unverified stored literal '
    parts['ppt/media/native.emf'] = build([
        font(1, 'Arial'), select(1),
        textw(raw=glyph_looking_digits.encode('utf-16le'), opts=0x10),
        textw(stored_clipped_literal, opts=0x4, x=500, y=600, rect=(1, 2, 3, 4)),
    ])
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    raw = output.getvalue()
    native = dm.build_document_manifest(raw, 'pptx', **IDENTITY)
    derived = dm.attach_document_visual_text(native, raw, expected_binding=native['binding'])
    observations = derived['native_emf_observations'][0]
    glyph, clipped = observations['observations']
    assert glyph['text'] is None and glyph['status'] == 'unsupported'
    assert glyph['raw_hex'] == glyph_looking_digits.encode('utf-16le').hex()
    assert any(row['code'] == 'glyph_index_text_unsupported' for row in observations['unsupported'])
    emf_units = [unit for unit in derived['units'] if unit['kind'] == 'emf_text']
    assert len(emf_units) == 1 and emf_units[0]['content'] == stored_clipped_literal
    assert emf_units[0]['coordinates']['native_emf']['logical_clip_rect'] == [1, 2, 3, 4]
    assert clipped['font']['kind'] == 'created'
    assert clipped['transform_state']['placement_status'] == 'unassessed'
    assert derived['visual_coverage'] == 'unassessed'
    smartart = [unit for unit in derived['units'] if unit['kind'].startswith('smartart_')]
    assert len(smartart) == 2 and smartart[0]['content'] == smartart[1]['content']
    assert {unit['origin'] for unit in smartart} == {
        'native_smartart_data_literal', 'stored_smartart_drawing_cache_unverified'}
    assert len({unit['id'] for unit in smartart}) == 2

    inventory = dg.evidence_inventory([derived], catalog_encoding=dg.CATALOG_ENCODING_V5)
    catalog = lc.complete_literal_catalog(inventory, catalog_encoding=lc.ENCODING_V2)
    quoteable = {unit['model_unit_id']: unit['content'] for unit in inventory['units']}
    assert glyph_looking_digits not in quoteable.values()
    assert stored_clipped_literal in quoteable.values()
    assert catalog['literal_coverage']['available_literal_unit_count'] == len(quoteable)
    assert catalog['reading_semantics'] == 'unassessed'
    assert all(catalog[key] == 'not_established' for key in
               ('financial_validation', 'regulatory_approval', 'investor_approval'))
