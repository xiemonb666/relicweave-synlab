"""Capabilities, registry, spec validation and the stage catalogue."""

from __future__ import annotations

from conftest import valid_spec


def test_capabilities_reports_missing_modules_verbatim(researcher):
    response = researcher.get("/api/synlab/capabilities", params={"doctor": "light", "refresh": True})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["prefix"] == "/api/synlab"
    assert body["session"]["role"] == "researcher"
    assert body["session"]["policy"]["can_read_truth"] is True
    assert body["worker"]["in_process_execution"] is False
    for key, module in body["modules"].items():
        assert module["status"] in ("OK", "DEPENDENCY_CAPABILITY_MISSING",
                                    "ENV_CAPABILITY_MISSING"), key
        if module["status"] != "OK":
            assert module["error"], f"{key} must carry the real reason"
    assert set(body["stage_requirements"]) >= {"freeze_spec", "audit", "generate", "training"}
    assert body["doctor"]["sqlite_integrity"] == "ok"
    # no server path leaks out of the API
    assert "store_root" not in response.text
    assert ":\\" not in response.text.replace("\\\\", "")


def test_capabilities_never_invents_missing_values(researcher):
    body = researcher.get("/api/synlab/capabilities").json()
    missing = set(body["missing"])
    available = set(body["available"])
    assert not missing & available
    for key in missing:
        assert body["modules"][key]["available"] is False


def test_registry_kind_and_unknown_kind(researcher):
    ok = researcher.get("/api/synlab/registry/vessel")
    assert ok.status_code == 200
    body = ok.json()
    assert body["kind"] == "vessel"
    assert body["registry_fingerprint"].startswith("sha256:")
    bad = researcher.get("/api/synlab/registry/unicorn")
    assert bad.status_code == 404
    assert bad.json()["error"]["code"] == "NOT_FOUND"


def test_registry_all_lists_every_kind(researcher):
    body = researcher.get("/api/synlab/registry/all").json()
    assert body["ok"] is True
    assert isinstance(body["entries"], list)


def test_specs_validate_rejects_unknown_field(researcher):
    spec = valid_spec()
    spec["totally_unknown_field"] = 17
    body = researcher.post("/api/synlab/specs/validate", json={"spec": spec}).json()
    assert body["ok"] is False
    assert body["rejected"] is True
    locations = [e["loc"] for e in body["errors"]]
    assert ["totally_unknown_field"] in locations
    assert all(e["type"] == "extra_forbidden" for e in body["errors"]
               if e["loc"] == ["totally_unknown_field"])


def test_specs_validate_rejects_units_and_range_violations(researcher):
    spec = valid_spec(units="cm")
    body = researcher.post("/api/synlab/specs/validate", json={"spec": spec}).json()
    assert body["ok"] is False
    spec2 = valid_spec()
    spec2["fracture"] = {"backend": "rough_shared_cut", "target_piece_range": [1, 2]}
    body2 = researcher.post("/api/synlab/specs/validate", json={"spec": spec2}).json()
    assert body2["ok"] is False
    assert any("target_piece_range" in e["msg"] or "target_piece_range" in ".".join(e["loc"])
               for e in body2["errors"])


def test_specs_validate_accepts_a_legal_spec(researcher):
    body = researcher.post("/api/synlab/specs/validate", json={"spec": valid_spec()}).json()
    assert body["ok"] is True, body["errors"]
    assert body["spec_hash"].startswith("sha256:")
    assert body["canonical"]


def test_specs_validate_unknown_kind_is_rejected(researcher):
    response = researcher.post("/api/synlab/specs/validate",
                               json={"spec": valid_spec(), "kind": "banana"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_request_body_unknown_field_is_rejected(researcher):
    response = researcher.post("/api/synlab/specs/validate",
                               json={"spec": valid_spec(), "mystery": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEMA_INVALID"


def test_stages_catalogue_exposes_capability_requirements(researcher):
    body = researcher.get("/api/synlab/stages").json()
    stages = {item["stage"]: item for item in body["stages"]}
    assert stages["generate"]["capabilities"]
    assert stages["freeze_spec"]["capabilities"] == []
    assert stages["audit"]["implemented_by"] == "synlab.api"
    assert stages["training"]["requires_gpu"] is True
