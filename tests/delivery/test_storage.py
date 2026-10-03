import pytest
from delivery.storage import read_bytes,read_source_bytes,store_bytes,scope_component


def test_scope_hash_integrity_and_symlink_rejection(tmp_path):
    root=tmp_path/'private'
    digest=store_bytes(root,'one','room',b'synthetic private fixture')
    assert read_bytes(root,'one','room',digest)==b'synthetic private fixture'
    with pytest.raises(OSError):read_bytes(root,'other','room',digest)
    with pytest.raises(ValueError):read_bytes(root,'one','room','../../elsewhere')
    target=root/scope_component('one')/scope_component('room')/digest
    target.unlink();target.symlink_to(tmp_path/'other-private-file')
    with pytest.raises(OSError):read_bytes(root,'one','room',digest)


def test_source_read_rejects_symlink_and_empty_file(tmp_path):
    source=tmp_path/'source.xlsx'
    source.write_bytes(b'synthetic workbook bytes')
    assert read_source_bytes(source)==b'synthetic workbook bytes'
    alias=tmp_path/'alias.xlsx'
    alias.symlink_to(source)
    with pytest.raises(OSError):read_source_bytes(alias)
    source.write_bytes(b'')
    with pytest.raises(ValueError):read_source_bytes(source)
