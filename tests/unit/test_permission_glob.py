from artcode.permissions.glob import glob_match


def test_path_star_does_not_cross_slash() -> None:
    assert glob_match("src/*.py", "src/a.py", path_mode=True)
    assert not glob_match("src/*.py", "src/a/b.py", path_mode=True)


def test_path_double_star_crosses_directories() -> None:
    assert glob_match("src/**/*.py", "src/a/b.py", path_mode=True)
    assert glob_match("src/**/*.py", "src/a.py", path_mode=True)


def test_matching_is_case_sensitive() -> None:
    assert not glob_match("src/**", "Src/a.py", path_mode=True)
