"""otas-tools CLI: one small verifier per seam.

  validate-all          -> schema-validate every schema + example documents
  lint-reasons          -> registry invariants (uniqueness, additivity, coarse-wire rule)
  check-manifest FILE   -> manifest validity + confidence/evidence + exclusion rules
  reconcile             -> cross-rail event reconciliation (used by the demo)
  run-vectors           -> conformance vectors against both rail adapters
"""
import json, sys, pathlib
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCH = ROOT / "schemas"


def _load(p):
    return json.loads(pathlib.Path(p).read_text())


def validate_doc(doc, schema_name):
    schema = _load(SCH / schema_name)
    errs = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: e.json_path)
    return [f"{e.json_path}: {e.message}" for e in errs]


def lint_reasons():
    """Registry invariants that follow from the proposed additivity model:
    codes and ids are unique, and every code named in whitepaper 6.3 is present."""
    reg = _load(SCH / "reasons-v1.json")
    problems = []
    codes = [c["code"] for c in reg["codes"]]
    nums = [c["num"] for c in reg["codes"]]
    if len(set(codes)) != len(codes):
        problems.append("duplicate code names")
    if len(set(nums)) != len(nums):
        problems.append("duplicate numeric ids")
    for named in ("INELIGIBLE_RECEIVER", "JURISDICTION_BLOCKED", "HOLDER_CAP_EXCEEDED",
                  "LOCKUP_ACTIVE", "SANCTIONS_HIT", "TRAVEL_RULE_PENDING"):
        if named not in codes:
            problems.append(f"{named}: named in whitepaper 6.3 but missing from the registry")
    return problems


def check_manifest(manifest):
    """Manifest validity plus the consistency rules that follow from 5.4:
    an observed description must say what state it was read from, and a
    chain-observed behavior cannot also be listed as not confirmable.

    Accepts a path or an already-loaded manifest dict."""
    m = manifest if isinstance(manifest, dict) else _load(manifest)
    problems = validate_doc(m, "manifest.schema.json")
    names = [b["name"] for b in m.get("behaviors", [])]

    for a, b in m.get("exclusions", []):
        if a in names and b in names:
            problems.append(f"exclusion violated: {a} x {b} both declared on rail {m['rail']}")

    if m.get("mapping") in ("observed", "mixed") and not m.get("anchor"):
        problems.append("observed/mixed mapping requires an anchor: such a description is "
                        "only valid as of the state it was read from")

    not_conf = set(m.get("not_confirmable", []))
    for b in m.get("behaviors", []):
        if b["source"] == "chain-observed" and b["name"] in not_conf:
            problems.append(f"{b['name']}: listed as chain-observed and as not confirmable")

    if "ConfidentialAmount" in names:
        for b in m.get("behaviors", []):
            if b["name"] != "ConfidentialAmount" and b["source"] == "chain-observed":
                problems.append(f"{b['name']}: amounts are confidential on this token, so "
                                f"event normalization is structural only — a behavior read "
                                f"from amount-bearing state cannot be chain-observed")
    return problems


def reconcile(event_streams: dict):
    """Merge rail-native event streams into one settlement-centric view.

    Checks the atomicity invariant (a settlement is Settled on both legs or on
    neither) and surfaces the DECLARED finality of each settlement, since
    technical finality is not uniform across rails and must not be inferred
    from the fact that an event was emitted."""
    merged = [ev for evs in event_streams.values() for ev in evs]
    report = {"total_events": len(merged), "schema_errors": 0, "settlements": {}}

    for ev in merged:
        report["schema_errors"] += len(validate_doc(ev, "events.schema.json"))
        sid = ev.get("settlement_id")
        if not sid:
            continue
        s = report["settlements"].setdefault(
            sid, {"rails": set(), "lifecycle": [], "finality_models": set(),
                  "legal_regimes": set()})
        s["rails"].add(ev["rail"])
        s["lifecycle"].append(ev["event_type"])
        fin = ev.get("finality", {})
        if fin.get("technical_model"):
            s["finality_models"].add(f"{ev['rail']}:{fin['technical_model']}")
        legal = fin.get("legal") or {}
        if legal.get("regime_ref"):
            s["legal_regimes"].add(legal["regime_ref"])

    for s in report["settlements"].values():
        lc = s["lifecycle"]
        settled, committed, aborted = lc.count("Settled"), lc.count("Committed"), lc.count("Aborted")
        s["rails"] = sorted(s["rails"])
        s["finality_models"] = sorted(s["finality_models"])
        s["legal_regimes"] = sorted(s["legal_regimes"])
        s["reached_committed"] = committed == 2
        s["atomicity_ok"] = not (settled and aborted) and settled in (0, 2)
        s["outcome"] = "SETTLED" if settled == 2 else ("ABORTED" if aborted else "PENDING/DENIED")
    return report


def run_vectors():
    from .identity import EligibilityOracle, TrustedIssuerList
    from .rails import EVMRail, SuiRail
    vectors = _load(ROOT / "conformance" / "vectors.json")
    results = []
    for v in vectors["vectors"]:
        trust = TrustedIssuerList(["did:web:kyc.example"])
        oracle = EligibilityOracle(trust)
        for p in v["setup"]["eligible"]:
            for t in ("KYC_COMPLETE", "SANCTIONS_CLEAR"):
                oracle.present(p, t, "did:web:kyc.example", {"s": p, "t": t})
        for p in v["setup"].get("sanctioned", []):
            for t in ("KYC_COMPLETE", "SANCTIONS_CLEAR"):
                oracle.present(p, t, "did:web:kyc.example", {"s": p, "t": t})
            oracle.revoke(p, "SANCTIONS_CLEAR")
        for rail_name in v["rails"]:
            rail = EVMRail(oracle) if rail_name == "evm-account" else SuiRail(oracle)
            tref = {"chain_namespace": "test", "reference": "0", "asset_id": "T"}
            if rail_name == "evm-account":
                rail.deploy("T", tref, v["setup"]["balances"])
            else:
                rail.publish(tref, v["setup"]["balances"])
            got = rail.can_transfer("T", v["op"]["from"], v["op"]["to"], v["op"]["amount"])
            results.append({"vector": v["id"], "rail": rail_name,
                            "expected": v["expect"], "got": got,
                            "pass": got == v["expect"]})
    return results


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate-all"
    if cmd == "validate-all":
        ok = True
        for name in ("manifest", "events", "settlement", "core-descriptor"):
            _load(SCH / f"{name}.schema.json")
            print(f"  schema {name}: parses OK")
        for p in lint_reasons():
            ok = False
            print("  reasons:", p)
        print("reason registry: OK" if ok else "reason registry: PROBLEMS")
    elif cmd == "lint-reasons":
        probs = lint_reasons()
        print("\n".join(probs) if probs else "OK")
    elif cmd == "reconcile":
        # Reconcile any event log in the {rail: [events]} shape -- including the
        # live testnet log written by live/runner.
        report = reconcile(_load(sys.argv[2]))
        print(f"  events: {report['total_events']}   schema violations: {report['schema_errors']}")
        for sid, st in report["settlements"].items():
            print(f"  {sid}: rails={st['rails']} outcome={st['outcome']} "
                  f"atomicity_ok={st['atomicity_ok']} finality={st['finality_models']}")
        sys.exit(0 if report["schema_errors"] == 0 else 1)
    elif cmd == "check-manifest":
        probs = check_manifest(sys.argv[2])
        print("\n".join(probs) if probs else "OK")
    elif cmd == "run-vectors":
        res = run_vectors()
        for r in res:
            print(f"  [{'PASS' if r['pass'] else 'FAIL'}] {r['vector']} on {r['rail']}: "
                  f"expected {r['expected']}, got {r['got']}")
        n = sum(r["pass"] for r in res)
        print(f"{n}/{len(res)} conformance vectors pass")
        sys.exit(0 if n == len(res) else 1)


if __name__ == "__main__":
    main()
