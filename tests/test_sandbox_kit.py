"""sandbox/ and the shell scripts around it: the files agree with each other, and the scripts
refuse bad input before touching anything. Nothing here needs the fork, Docker or the shop."""

import re
import subprocess

import pytest
import yaml

from app.settings import ROOT

KIT = ROOT / "sandbox"


class ComposeLoader(yaml.SafeLoader):
    """Reads compose files, whose `!reset` tag plain YAML doesn't know."""


ComposeLoader.add_constructor("!reset", lambda loader, node: "!reset")


def compose_versions() -> dict:
    return yaml.load((KIT / "overlay" / "compose.versions.yaml").read_text(), ComposeLoader)


def env_file(path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def version_var(service: str) -> str:
    """The versions.env name, as deploy.sh derives it: tr 'a-z-' 'A-Z_'."""
    return service.upper().replace("-", "_") + "_VERSION"


def test_versioned_services_are_the_same_everywhere():
    in_compose = set(compose_versions()["services"])
    build = (KIT / "build-images.sh").read_text()
    in_build = set(re.search(r"ALL_SERVICES=\(([^)]*)\)", build).group(1).split())
    deploy = (ROOT / "scenarios" / "deploy.sh").read_text()
    in_deploy = {s.strip() for s in re.search(r"\n  ([a-z| -]+)\) ;;", deploy).group(1).split("|")}
    owned = set(yaml.safe_load((ROOT / "config" / "ownership.yaml").read_text()))
    assert (
        in_compose == in_build == in_deploy == {"payment", "quote", "checkout", "product-catalog"}
    )
    assert in_compose <= owned


def test_compose_versions_switches_only_image_and_service_version():
    for service, spec in compose_versions()["services"].items():
        var = version_var(service)
        assert spec["image"] == f"sandbox/{service}:${{{var}:-v1.3.0}}"
        assert spec["build"] == "!reset" and spec["pull_policy"] == "never"
        [attrs] = [e for e in spec["environment"] if e.startswith("OTEL_RESOURCE_ATTRIBUTES=")]
        assert re.fullmatch(
            rf"OTEL_RESOURCE_ATTRIBUTES=service\.namespace=\$\{{OTEL_SERVICE_NAMESPACE\}},"
            rf"service\.version=\$\{{{var}:-v1\.3\.0\}},service\.criticality=(critical|high|low)",
            attrs,
        ), attrs


def test_scenario_reads_versions_env_with_deploy_sh_names(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT / "scenarios"))
    import scenario

    (tmp_path / "versions.env").write_text("PRODUCT_CATALOG_VERSION=v1.4.0\n")
    monkeypatch.setattr(scenario, "SANDBOX_DIR", tmp_path)
    assert scenario.deployed("product-catalog") == "v1.4.0"
    assert scenario.deployed("payment") == "v1.3.0"  # nothing deployed yet


def test_upstream_pin():
    env = env_file(KIT / "upstream.env")
    assert re.fullmatch(r"[0-9a-f]{40}", env["UPSTREAM_SHA"])
    assert env["UPSTREAM_REF"] == "3.1.0"
    assert all(re.fullmatch(r"[0-9a-f]{8}", env[k]) for k in ("EXPECTED_V1_3_0", "EXPECTED_V1_4_0"))


def test_patch_series():
    for tag, count in (("v1.3.0", 1), ("v1.4.0", 8)):
        patches = sorted((KIT / "patches" / tag).glob("*.patch"))
        assert [p.name[:4] for p in patches] == [f"{n:04d}" for n in range(1, count + 1)]
        for n, p in enumerate(patches, 1):
            text = p.read_text()
            subject = f"[PATCH {n}/{count}]" if count > 1 else "[PATCH]"
            assert text.startswith("From 0000000000000000000000000000000000000000")
            assert f"Subject: {subject}" in text, p.name


def test_overlay_pins_the_other_services_to_the_release():
    env = env_file(KIT / "overlay" / ".env.override")
    assert env["DEMO_VERSION"] == env["IMAGE_VERSION"] == "3.1.0"
    assert "service.version=${IMAGE_VERSION}" in env["OTEL_RESOURCE_ATTRIBUTES"]


def script(name: str, *args: str, sandbox_dir, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(ROOT / name), *args],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "SANDBOX_DIR": str(sandbox_dir),
            **env,
        },
        timeout=30,
    )


@pytest.fixture
def empty_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_deploy_refuses_an_unversioned_service(empty_repo):
    r = script("scenarios/deploy.sh", "frontend", "v1.4.0", sandbox_dir=empty_repo)
    assert r.returncode == 1 and "isn't versioned" in r.stderr


def test_deploy_refuses_an_unknown_tag(empty_repo):
    r = script("scenarios/deploy.sh", "payment", "v9.9.9", sandbox_dir=empty_repo)
    assert r.returncode == 1 and "no tag v9.9.9" in r.stderr
    assert not (empty_repo / "versions.env").exists()  # nothing changed


def test_build_images_refuses_an_unversioned_service(empty_repo):
    r = script("sandbox/build-images.sh", "cart", sandbox_dir=empty_repo)
    assert r.returncode == 1 and "cart isn't versioned" in r.stderr


def test_setup_refuses_a_dirty_sandbox(empty_repo):
    """setup.sh rebuilds the sandbox branch from scratch, so it must not run over edits."""
    (empty_repo / "f").write_text("x")
    git = ["git", "-C", str(empty_repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "f"], check=True)
    subprocess.run([*git, "commit", "-qm", "f"], check=True)
    (empty_repo / "f").write_text("changed")
    r = script("sandbox/setup.sh", sandbox_dir=empty_repo)
    assert r.returncode == 1 and "uncommitted changes" in r.stderr


def test_make_targets_exist():
    targets = set(re.findall(r"^([a-z%-]+):", (ROOT / "Makefile").read_text(), re.M))
    wanted = {
        "sandbox",
        "sandbox-images",
        "shop-up",
        "shop-down",
        "scenario-%",
        "deploy",
        "flag",
        "test-sandbox",
        "test-shop",
    }
    assert wanted <= targets
