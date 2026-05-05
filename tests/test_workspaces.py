"""Workspace registry: ключи, default, получение."""

from bot.domain.workspaces import (
    DEFAULT_WORKSPACE,
    WORKSPACES,
    all_keys,
    get,
)


def test_registry_contains_expected_keys():
    keys = all_keys()
    assert keys == ("personal", "work", "family", "growth", "ai_path")


def test_default_workspace_resolves():
    w = get(DEFAULT_WORKSPACE)
    assert w.key == DEFAULT_WORKSPACE
    assert w.label  # не пустое


def test_unknown_key_falls_back_to_default():
    w = get("does_not_exist")
    assert w.key == DEFAULT_WORKSPACE


def test_each_workspace_has_unique_space_env():
    envs = [w.space_env for w in WORKSPACES]
    assert len(envs) == len(set(envs))
    assert all(env.startswith("BUILDIN_SPACE_") for env in envs)


def test_each_workspace_has_label_and_description():
    for w in WORKSPACES:
        assert w.label
        assert w.description
