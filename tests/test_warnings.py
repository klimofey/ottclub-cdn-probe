"""Warnings about settings that quietly do nothing."""
import importlib, os
import pytest


def reload_with(**env):
    for k in ("AUTO_APPLY", "ACTIVE_HOURS", "ROUND_PAUSE"):
        os.environ.pop(k, None)
    os.environ.update(env)
    from cdnprobe import config
    importlib.reload(config)
    return config


class TestSettingsWarnings:
    def test_auto_apply_with_continuous_rounds_is_pointless(self):
        """The next round switches the CDN away within minutes."""
        c = reload_with(AUTO_APPLY="true", ROUND_PAUSE="none")
        notes = c.settings_warnings()
        assert any("AUTO_APPLY" in n for n in notes)

    def test_auto_apply_is_fine_with_a_long_pause(self):
        c = reload_with(AUTO_APPLY="true", ROUND_PAUSE="6h")
        assert not any("AUTO_APPLY has no lasting" in n
                       for n in c.settings_warnings())

    def test_auto_apply_is_fine_with_active_hours(self):
        c = reload_with(AUTO_APPLY="true", ROUND_PAUSE="none",
                        ACTIVE_HOURS="01:00-07:00")
        assert not any("AUTO_APPLY has no lasting" in n
                       for n in c.settings_warnings())

    def test_active_hours_without_auto_apply_is_flagged(self):
        """Otherwise the account is left on whatever was tested last."""
        c = reload_with(ACTIVE_HOURS="01:00-07:00", AUTO_APPLY="false")
        assert any("ACTIVE_HOURS is set" in n for n in c.settings_warnings())

    def test_plain_defaults_warn_about_nothing(self):
        c = reload_with()
        assert c.settings_warnings() == []
