import pytest

from app.storage import UnsafePathError, book_dir, create_book_dirs, new_book_uuid, safe_join


def test_create_book_dirs(tmp_path):
    book_uuid = new_book_uuid()
    root = create_book_dirs(tmp_path, book_uuid)
    for name in ("pages", "ocr", "corrected", "translations", "exports"):
        assert (root / name).is_dir()


@pytest.mark.parametrize("bad", ["../etc", "..", "abc", "a" * 32 + "/x", ""])
def test_book_dir_rejects_bad_ids(tmp_path, bad):
    with pytest.raises(UnsafePathError):
        book_dir(tmp_path, bad)


def test_safe_join_blocks_traversal(tmp_path):
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "..", "secret.txt")


def test_safe_join_allows_children(tmp_path):
    assert safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()
