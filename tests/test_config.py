from __future__ import annotations

from pathlib import Path

import pytest

from massive_access import MassiveClient, MissingAPIKeyError, get_api_key
from massive_access.config import ENV_API_KEY, ENV_CONFIG_FILE, key_file_candidates


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """No env key, no key file; tests opt into what they need."""
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    monkeypatch.delenv(ENV_CONFIG_FILE, raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # ~/.config lands in tmp
    monkeypatch.setattr("massive_access.config.Path.home", lambda: tmp_path)


def write_key_file(tmp_path, content: str) -> str:
    path = tmp_path / "keyfile"
    path.write_text(content)
    return str(path)


# -- resolution order -------------------------------------------------------


def test_explicit_argument_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_API_KEY, "from-env")
    file = write_key_file(tmp_path, "from-file")
    monkeypatch.setenv(ENV_CONFIG_FILE, file)
    assert get_api_key("explicit") == "explicit"


def test_env_var_beats_file(monkeypatch, tmp_path):
    file = write_key_file(tmp_path, "from-file")
    monkeypatch.setenv(ENV_CONFIG_FILE, file)
    monkeypatch.setenv(ENV_API_KEY, "from-env")
    assert get_api_key() == "from-env"


def test_key_file_plain_line(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_CONFIG_FILE, write_key_file(tmp_path, "from-file\n"))
    assert get_api_key() == "from-file"


def test_key_file_assignment_form(monkeypatch, tmp_path):
    monkeypatch.setenv(
        ENV_CONFIG_FILE, write_key_file(tmp_path, f"{ENV_API_KEY}=from-file\n")
    )
    assert get_api_key() == "from-file"


def test_key_file_quotes_and_comments(monkeypatch, tmp_path):
    monkeypatch.setenv(
        ENV_CONFIG_FILE,
        write_key_file(tmp_path, "# comment\n\n  'from-file'  \nOTHER=x\n"),
    )
    assert get_api_key() == "from-file"


def test_key_file_empty_assignment_keeps_looking(monkeypatch, tmp_path):
    monkeypatch.setenv(
        ENV_CONFIG_FILE, write_key_file(tmp_path, f"{ENV_API_KEY}=  \nKEY=good\n")
    )
    assert get_api_key() == "good"


def test_blank_env_falls_through_to_file(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_API_KEY, "   ")
    monkeypatch.setenv(ENV_CONFIG_FILE, write_key_file(tmp_path, "from-file\n"))
    assert get_api_key() == "from-file"


def test_unreadable_key_file_is_ignored(monkeypatch, tmp_path):
    file = tmp_path / "keyfile"
    file.write_text("from-file\n")
    file.chmod(0o000)
    monkeypatch.setenv(ENV_CONFIG_FILE, str(file))
    with pytest.raises(MissingAPIKeyError):
        get_api_key()


def test_explicit_empty_string_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_CONFIG_FILE, write_key_file(tmp_path, "from-file\n"))
    assert get_api_key("") == "from-file"


# -- fallback candidates and errors ------------------------------------------


def test_candidate_order_includes_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_CONFIG_FILE, "/somewhere/key")
    paths = key_file_candidates()
    assert paths[0] == Path("/somewhere/key")
    assert str(paths[-1]) == "/etc/massive-access/key"


def test_missing_everywhere_raises_with_locations(monkeypatch, tmp_path):
    with pytest.raises(MissingAPIKeyError) as exc:
        get_api_key()
    assert ENV_API_KEY in str(exc.value)
    assert "massive.com" in str(exc.value)
    assert str(tmp_path / ".config" / "massive-access" / "key") in str(exc.value)


def test_client_requires_key():
    with pytest.raises(MissingAPIKeyError):
        MassiveClient()


# -- CLI diagnostic -----------------------------------------------------------


def test_cli_key_reports_source(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(ENV_CONFIG_FILE, write_key_file(tmp_path, "from-file\n"))
    from massive_access.cli import main as cli_main

    assert cli_main(["key"]) == 0
    out = capsys.readouterr().out
    assert "keyfile" in out
    assert "from-file" not in out  # never the key itself


def test_cli_key_fails_without_key(monkeypatch, capsys):
    from massive_access.cli import main as cli_main

    assert cli_main(["key"]) == 1
    assert "no API key found" in capsys.readouterr().err
