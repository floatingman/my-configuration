#!/usr/bin/env python3
"""Tests for CLI subcommand integration."""

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import main  # noqa: E402


class TestCLIResolve:
    """Tests for the 'resolve' CLI subcommand."""

    def test_resolve_named_profile_outputs_json(self, capsys):
        """resolve --profile i3 should print valid JSON and exit 0."""
        rc = main(["resolve", "--profile", "i3"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "i3"
        assert data["is_i3"] is True
        assert data["display_manager"] == "lightdm"
        assert data["has_display"] is True

    def test_resolve_headless_profile(self, capsys):
        """resolve --profile headless should have has_display=False."""
        rc = main(["resolve", "--profile", "headless"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["has_display"] is False
        assert data["display_manager"] is None

    def test_resolve_manual_mode_with_display_manager(self, capsys):
        """resolve --display-manager lightdm outputs manual mode JSON."""
        rc = main(["resolve", "--display-manager", "lightdm"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "manual"
        assert data["display_manager"] == "lightdm"
        assert data["has_display"] is True

    def test_resolve_with_disable_flags(self, capsys):
        """resolve with disable flags suppresses the relevant DE."""
        rc = main(["resolve", "--display-manager", "lightdm", "--disable-i3"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["is_i3"] is False
        assert data["is_hyprland"] is True

    def test_resolve_unknown_profile_exits_1(self, capsys):
        """resolve --profile unknown exits 1 and writes error to stderr."""
        rc = main(["resolve", "--profile", "unknown_profile"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Unknown profile" in err
        assert "unknown_profile" in err

    def test_resolve_json_matches_resolved_profile_schema(self, capsys):
        """resolve JSON contains all ResolvedProfile fields."""
        main(["resolve", "--profile", "gnome"])
        out = capsys.readouterr().out
        data = json.loads(out)
        expected_keys = {
            "profile", "display_manager", "has_display",
            "desktop_environment", "is_i3", "is_hyprland",
            "is_gnome", "is_awesomewm", "is_kde",
        }
        assert expected_keys == set(data.keys())



class TestCLIValidate:
    """Tests for the 'validate' CLI subcommand."""

    def test_validate_real_profiles_exits_0(self, capsys):
        """validate against the real profiles directory should exit 0."""
        rc = main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "" or out.strip() == ""

    def test_validate_with_invalid_profile_exits_1(self, capsys):
        """validate exits 1 and writes errors to stderr when a profile is invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "bad.yml").write_text("name: missing_required\n")
            rc = main(["validate", "--profiles-dir", tmpdir])
        err = capsys.readouterr().err
        assert rc == 1
        assert "bad" in err

    def test_validate_empty_dir_exits_0(self, capsys):
        """validate exits 0 when there are no non-underscore profiles to check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "_base.yml").write_text("name: base\n")
            rc = main(["validate", "--profiles-dir", tmpdir])
        assert rc == 0

    def test_validate_error_goes_to_stderr_not_stdout(self, capsys):
        """validate writes errors to stderr and nothing to stdout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "bad.yml").write_text("name: broken\n")
            main(["validate", "--profiles-dir", tmpdir])
        out = capsys.readouterr().out
        # stdout should be empty; error belongs in stderr
        assert out == ""



class TestCLIListProfiles:
    """Tests for the 'list-profiles' CLI subcommand."""

    def test_list_profiles_names_format(self, capsys):
        """list-profiles --format names outputs space-separated profile names."""
        rc = main(["list-profiles", "--format", "names"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        names = out.split()
        assert set(names) == {"awesomewm", "gnome", "headless", "hyprland", "i3", "kde"}

    def test_list_profiles_default_format_is_names(self, capsys):
        """list-profiles with no --format defaults to names."""
        rc = main(["list-profiles"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert " " in out  # space-separated, multiple names

    def test_list_profiles_pretty_format(self, capsys):
        """list-profiles --format pretty outputs a table with header."""
        rc = main(["list-profiles", "--format", "pretty"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "NAME" in out
        assert "DESCRIPTION" in out
        assert "DISPLAY_MANAGER" in out
        assert "DESKTOP_ENVIRONMENT" in out
        # Table should include each profile
        for name in ("awesomewm", "gnome", "headless", "hyprland", "i3", "kde"):
            assert name in out

    def test_list_profiles_pretty_format_includes_display_manager(self, capsys):
        """pretty table includes display_manager values."""
        main(["list-profiles", "--format", "pretty"])
        out = capsys.readouterr().out
        assert "lightdm" in out
        assert "gdm" in out
        assert "sddm" in out

    def test_list_profiles_custom_dir(self, capsys):
        """list-profiles respects --profiles-dir."""
        valid = "display_manager_default: lightdm\ndesktop_environment: i3\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "myprofile.yml").write_text(valid)
            rc = main(["list-profiles", "--profiles-dir", tmpdir])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert "myprofile" in out



class TestCLIMakeArgs:
    """Tests for the 'make-args' CLI subcommand."""

    def test_make_args_i3_profile(self, capsys):
        """make-args --profile i3 outputs -e flag string with correct values."""
        rc = main(["make-args", "--profile", "i3"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out.startswith('-e "')
        assert out.endswith('"')
        assert "profile=i3" in out
        assert "desktop_environment=i3" in out
        assert "display_manager=lightdm" in out

    def test_make_args_headless_profile(self, capsys):
        """make-args --profile headless omits optional fields with empty values."""
        rc = main(["make-args", "--profile", "headless"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert "profile=headless" in out
        # headless has no display_manager or desktop_environment
        assert "desktop_environment" not in out
        assert "display_manager" not in out

    def test_make_args_unknown_profile_exits_1(self, capsys):
        """make-args with unknown profile exits 1 and writes to stderr."""
        rc = main(["make-args", "--profile", "bogus"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "bogus" in err or "Unknown profile" in err

    def test_make_args_output_is_shell_safe(self, capsys):
        """make-args output is wrapped in double quotes for shell safety."""
        main(["make-args", "--profile", "gnome"])
        out = capsys.readouterr().out.strip()
        assert out.startswith('-e "')
        assert out.endswith('"')



class TestCLIUnknownSubcommand:
    """Tests for unknown subcommand handling."""

    def test_no_subcommand_exits_1(self, capsys):
        """Running with no subcommand exits 1 and prints usage."""
        rc = main([])
        assert rc == 1

    def test_no_subcommand_prints_usage(self, capsys):
        """Running with no subcommand prints usage to stderr."""
        main([])
        err = capsys.readouterr().err
        assert "usage" in err.lower()

    def test_unknown_subcommand_exits_1(self, capsys):
        """An unrecognised subcommand returns 1 rather than raising SystemExit(2)."""
        rc = main(["not-a-real-subcommand"])
        assert rc == 1

    def test_unknown_subcommand_prints_usage(self, capsys):
        """An unrecognised subcommand prints usage to stderr."""
        main(["not-a-real-subcommand"])
        err = capsys.readouterr().err
        assert "usage" in err.lower()





class TestCLIValidateOverlays:
    """Tests for the 'validate' CLI subcommand with overlay validation."""

    def test_validate_with_invalid_overlay_exits_1(self, capsys):
        """validate exits 1 when an overlay file is structurally invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir()

            # Create a valid profile
            Path(tmpdir, "headless.yml").write_text(
                "display_manager_default: ''\ndesktop_environment: ''\n"
            )

            # Create an invalid overlay (missing applies_when)
            (overlays_dir / "bad.yml").write_text(
                "name: Bad Overlay\nroles:\n  - {role: test, tags: [test]}\n"
            )

            rc = main(["validate", "--profiles-dir", tmpdir])
            assert rc == 1
            err = capsys.readouterr().err
            assert "overlay" in err.lower()



class TestCLIResolveRoleManifest:
    """Tests for the 'resolve-role-manifest' CLI subcommand."""

    def test_resolve_manifest_named_profile(self, capsys):
        """resolve-manifest --profile i3 outputs valid JSON."""
        rc = main(["resolve-role-manifest", "--profile", "i3"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "i3"
        assert data["display_manager"] == "lightdm"
        assert data["has_display"] is True
        assert "profile_flags" in data
        assert "overlay_flags" in data
        assert "roles" in data

    def test_resolve_manifest_headless_profile(self, capsys):
        """resolve-manifest --profile headless outputs manifest with no display."""
        rc = main(["resolve-role-manifest", "--profile", "headless"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "headless"
        assert data["has_display"] is False
        assert data["display_manager"] is None

    def test_resolve_role_manifest_with_host_vars(self, capsys):
        """resolve-role-manifest --host-vars evaluates config_check expressions."""
        host_vars_json = json.dumps({"laptop": True})
        rc = main(["resolve-role-manifest", "--profile", "i3", "--host-vars", host_vars_json])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert "_overlay_laptop" in data["overlay_flags"]

    def test_resolve_manifest_invalid_host_vars_exits_1(self, capsys):
        """resolve-manifest with invalid JSON in --host-vars exits 1."""
        rc = main(["resolve-role-manifest", "--profile", "i3", "--host-vars", "invalid json"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Invalid JSON" in err

    def test_resolve_manifest_manual_mode(self, capsys):
        """resolve-manifest works in manual mode without --profile."""
        rc = main([
            "resolve-role-manifest",
            "--display-manager", "lightdm",
            "--desktop-environment", "i3",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "manual"
        assert data["display_manager"] == "lightdm"

    def test_resolve_manifest_roles_have_required_fields(self, capsys):
        """resolve-manifest output includes all required role fields."""
        main(["resolve-role-manifest", "--profile", "hyprland"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "roles" in data
        assert len(data["roles"]) > 0
        first_role = data["roles"][0]
        assert "role" in first_role
        assert "tags" in first_role
        assert "condition" in first_role
        assert "source" in first_role

    def test_resolve_manifest_unknown_profile_exits_1(self, capsys):
        """resolve-manifest with unknown profile exits 1."""
        rc = main(["resolve-role-manifest", "--profile", "unknown"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Unknown profile" in err


class TestCLIGeneratePlaybook:
    """Tests for the 'generate-playbook' CLI subcommand."""

    def test_generate_playbook_outputs_valid_yaml(self, capsys):
        """generate-playbook should write a valid playbook YAML file."""
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as tmp:
            tmpfile = tmp.name
        try:
            rc = main(["generate-playbook", "--write", tmpfile])
            assert rc == 0
            with open(tmpfile) as f:
                parsed = yaml.safe_load(f)
            assert isinstance(parsed, list)
            play = parsed[0]
            assert "roles" in play
            assert isinstance(play["roles"], list)
            assert any(
                (
                    isinstance(role, dict) and role.get("role") in {"shell", "base"}
                )
                for role in play["roles"]
            )
        finally:
            os.unlink(tmpfile)

    def test_generate_playbook_stdout_mode(self, capsys):
        """generate-playbook without --write should output role manifest JSON to stdout."""
        rc = main(["generate-playbook"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        # Verify output is valid JSON
        output = json.loads(captured.out)
        assert "os_family" in output
        assert "profiles" in output
        assert "roles" in output
        # Verify roles structure
        assert isinstance(output["roles"], list)
        if len(output["roles"]) > 0:
            role = output["roles"][0]
            assert "role" in role
            assert "tags" in role
            assert "condition" in role
            assert "source" in role

    def test_generate_playbook_output_includes_tags(self, capsys):
        """generate-playbook output should include tags for each role."""
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as tmp:
            tmpfile = tmp.name
        try:
            main(["generate-playbook", "--write", tmpfile])
            with open(tmpfile) as f:
                parsed = yaml.safe_load(f)
            play = parsed[0]
            dict_roles = [r for r in play["roles"] if isinstance(r, dict)]
            # Most roles should have tags
            with_tags = [r for r in dict_roles if "tags" in r]
            assert len(with_tags) > 0, "Expected at least one role with tags"
            # Tags should be lists of strings
            for role in with_tags:
                assert isinstance(role["tags"], list)
                assert all(isinstance(t, str) for t in role["tags"])
        finally:
            os.unlink(tmpfile)

    def test_generate_playbook_custom_dir(self, capsys):
        """generate-playbook respects --profiles-dir."""
        valid = "display_manager_default: lightdm\ndesktop_environment: i3\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "myprofile.yml").write_text(valid)
            outfile = str(Path(tmpdir) / "output.yml")
            rc = main(["generate-playbook", "--profiles-dir", tmpdir, "--write", outfile])
            assert rc == 0
            with open(outfile) as f:
                parsed = yaml.safe_load(f)
            assert "roles" in parsed[0]

    def test_generate_playbook_bad_dir_exits_1(self, capsys):
        """generate-playbook with nonexistent profiles-dir exits 1."""
        rc = main(["generate-playbook", "--profiles-dir", "/nonexistent/path"])
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "does not exist" in captured.err



