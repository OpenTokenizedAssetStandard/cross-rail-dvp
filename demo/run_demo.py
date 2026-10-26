#!/usr/bin/env python3
"""OTAS end-to-end demo: cross-rail DvP between Ethereum and Sui.

Whitepaper Flow A, executed step by step. Each step names the OTAS INTERFACE
exercised; enforcement of each step binds to whatever native mechanism the rail
provides (whitepaper 5.3), and the two rails here are deliberately unalike:

  Ethereum rail  account/balance state; compliance in ERC-3643 registries and
                 modular compliance contracts, evaluated at transfer.
  Sui rail       Permissioned Asset Standard: ownership in shared Account
                 objects, a Policy<T> naming the approval witnesses each action
                 requires, and a create -> approve -> resolve request that is a
                 hot potato -- it resolves in the same transaction or the
                 transaction aborts.

`canTransfer` below is the OTAS interface convention, not the ERC-3643 function
of the same name. That is the whole point: the same query shape and the same
result vocabulary over two completely different enforcement mechanisms.

Scenarios: (A) happy path  (B) sanctions revocation, nothing locks
           (C) a leg's state is not held before timeout -> Aborted, refunds.
"""
import json, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from otas_tools.identity import EligibilityOracle, TrustedIssuerList
from otas_tools.rails import EVMRail, SuiRail
from otas_tools.coordinator import SettlementCoordinator
from otas_tools.cli import check_manifest, reconcile

ROOT = pathlib.Path(__file__).resolve().parents[1]

BOND_REF = {"chain_namespace": "eip155", "reference": "1", "asset_id": "0xB0ND...2031"}
DEP_REF = {"chain_namespace": "sui", "reference": "mainnet", "asset_id": "0x...::deposit::DEPOSIT"}

# --- Section 5.4: the same OTAS object, two different provenances -----------

# The bond predates any OTAS labelling, so tooling read what it could from
# chain state and the issuer supplied the rest: a MIXED mapping.
BOND_MANIFEST = {
    "spec_version": "1.0.0", "token_ref": BOND_REF, "rail": "evm-account",
    "base_type": "FractionalUniqueBase",
    "mapping": "mixed",
    "anchor": {"block": "21,845,003", "read_at": "2026-09-22T06:00:00Z",
               "code_hash": "0x7c1d...proxy-impl"},
    "behaviors": [
        {"name": "Restricted", "source": "chain-observed",
         "binding": "ERC-3643 canTransfer/isVerified via Identity Registry"},
        {"name": "Freezable", "source": "chain-observed", "binding": "agent freeze"},
        {"name": "ForceTransferable", "source": "chain-observed",
         "binding": "ERC-3643 forced transfer"},
        {"name": "AtomicLeg", "source": "issuer-declared",
         "binding": "OTASHTLCLeg escrow",
         "corroboration_ref": "ipfs://QmAtomicLegIntegrationNote"},
        {"name": "IncomeBearing", "source": "issuer-declared",
         "binding": "agent coupon distribution",
         "corroboration_ref": "ipfs://QmCouponTermsAttestation"},
    ],
    "not_confirmable": ["Recoverable", "CorporateActionable"],
    "exclusions": [],
    "policy_refs": ["0xREG...identity-registry", "0xCMP...modular-compliance"],
    "settlement_asset_tier": "not-cash",
    "metadata_anchor": "0x5e7a...bond-descriptor",
}

# The deposit token was issued to conform: a NATIVE mapping, with the PAS
# Policy<T> itself readable before any request is submitted.
DEPOSIT_MANIFEST = {
    "spec_version": "1.0.0", "token_ref": DEP_REF, "rail": "sui-object",
    "base_type": "FungibleBase",
    "mapping": "native",
    "behaviors": [
        {"name": "Restricted", "source": "issuer-declared",
         "binding": "Sui PAS Policy<T> send_funds + IssuerComplianceWitness"},
        {"name": "Freezable", "source": "issuer-declared",
         "binding": "withheld PAS approval (and DenyCapV2 + system DenyList)"},
        {"name": "Pausable", "source": "issuer-declared", "binding": "DenyList global pause"},
        {"name": "ForceTransferable", "source": "issuer-declared",
         "binding": "PAS clawback_funds, gated by the same Policy<T>"},
        {"name": "AtomicLeg", "source": "issuer-declared",
         "binding": "policy-recognized escrow account + hashlock"},
        {"name": "Mintable", "source": "issuer-declared", "binding": "TreasuryCap"},
    ],
    "not_confirmable": [],
    "exclusions": [["ConfidentialAmount", "Restricted"]],
    "policy_refs": ["0xPOLICY...deposit"],
    "settlement_asset_tier": "commercial-bank-deposit",
    "metadata_anchor": "0x91cc...deposit-descriptor",
}


def banner(s):
    print(f"\n{'=' * 74}\n  {s}\n{'=' * 74}")


def step(n, s):
    print(f"\n[{n}] {s}")


def build_world():
    trust = TrustedIssuerList(["did:web:kyc.bank-a.example", "did:web:kyc.fund-b.example"])
    oracle = EligibilityOracle(trust)
    for party, issuer in (("fund-b", "did:web:kyc.fund-b.example"),
                          ("bank-a-dealer", "did:web:kyc.bank-a.example")):
        for topic in ("KYC_COMPLETE", "SANCTIONS_CLEAR"):
            oracle.present(party, topic, issuer,
                           {"subject": party, "topic": topic, "assurance": "high"})
    evm, sui = EVMRail(oracle), SuiRail(oracle)
    evm.deploy("BOND31", BOND_REF, {"bank-a-dealer": 1_000_000})
    sui.publish(DEP_REF, {"fund-b": 5_000_000})
    return oracle, evm, sui


def make_legs(evm, sui, qty_bond, qty_cash):
    """Each leg declares its own technical finality model and its own legal
    finality construct. Note the two rulebooks disagree about Abort after
    Committed -- which is exactly the kind of thing the whitepaper leaves to
    the rulebook, and which a coordinator therefore has to reconcile."""
    return [
        {"leg_id": "leg-asset", "role": "asset", "token": "BOND31", "token_ref": BOND_REF,
         "rail": "evm-account", "rail_obj": evm, "from": "bank-a-dealer", "to": "fund-b",
         "amount": qty_bond, "settlement_asset_tier": "not-cash",
         "finality": {
             "technical_model": "probabilistic", "confirmation_depth": 12,
             "legal": {"regime_ref": "rulebook:designated-system-X",
                       "rulebook_hash": "0xa11c...",
                       "irrevocability_moment": "Committed",
                       "final_settlement_moment": "Settled",
                       "abort_after_committed": False}}},
        {"leg_id": "leg-cash", "role": "cash", "token": "DEPOSIT", "token_ref": DEP_REF,
         "rail": "sui-object", "rail_obj": sui, "from": "fund-b", "to": "bank-a-dealer",
         "amount": qty_cash, "settlement_asset_tier": "commercial-bank-deposit",
         "finality": {
             "technical_model": "deterministic",
             "legal": {"regime_ref": "rulebook:bank-a-deposit-token-terms-v3",
                       "rulebook_hash": "0xbee5...",
                       "irrevocability_moment": "Committed",
                       "final_settlement_moment": "Settled",
                       "abort_after_committed": True}}},
    ]


def main():
    banner("OTAS e2e cross-rail DvP — tokenized sovereign bond (Ethereum) "
           "against tokenized deposit (Sui)")

    step("A.1", "Both tokens modeled as OTAS objects (5.4: native vs observed)")
    for label, m in (("bond / evm", BOND_MANIFEST), ("deposit / sui", DEPOSIT_MANIFEST)):
        probs = check_manifest(m)
        declared = [b["name"] for b in m["behaviors"] if b["source"] == "issuer-declared"]
        observed = [b["name"] for b in m["behaviors"] if b["source"] == "chain-observed"]
        print(f"    {label}: mapping={m['mapping']}  manifest={'OK' if not probs else probs}")
        print(f"      chain-observed : {observed or '—'}")
        print(f"      issuer-declared: {declared or '—'}")
        if m["not_confirmable"]:
            print(f"      not confirmable from chain state alone: {m['not_confirmable']}")
        if m["exclusions"]:
            print(f"      mutually exclusive on this rail: {m['exclusions']}")
    print("\n    The bond is a MIXED mapping, valid only as of its anchor block; the deposit")
    print("    is NATIVE, and its PAS Policy<T> is readable before any request is submitted.")
    print("    Both are the same kind of OTAS object downstream — only the provenance differs,")
    print("    and how much corroboration a declared behavior needs is still an open question.")

    oracle, evm, sui = build_world()
    coord = SettlementCoordinator()

    # ---------------------------- Scenario A ----------------------------
    banner("Scenario A — happy path: 100,000 bond units against 2,500,000 deposit units")

    step("A.2", "Identity interface — eligibility proofs; no PII moves")
    for p in ("fund-b", "bank-a-dealer"):
        print(f"    isEligible({p}) = {oracle.is_eligible(p)}   (audit records a party HASH only)")

    step("A.3", "Compliance interface (canTransfer) — a PRE-SETTLEMENT check")
    legs = make_legs(evm, sui, 100_000, 2_500_000)
    sid = coord.propose(legs)
    for leg in legs:
        code = coord.presettlement_check(sid)[leg["leg_id"]]
        print(f"    {leg['leg_id']:<10} {code:<22} binding: "
              f"{'ERC-3643 registries + modular compliance' if leg['rail'] == 'evm-account' else 'PAS Policy<T> resolved by approval witnesses'}")
    print("    Same query shape, same result vocabulary, two unrelated enforcement mechanisms.")

    step("A.4", "Settlement interface (AtomicLeg / SettlementProposed)")
    print(f"    cash-leg trust tier declared: commercial-bank-deposit")
    for leg in legs:
        f = leg["finality"]
        depth = f" (depth {f['confirmation_depth']})" if f.get("confirmation_depth") else ""
        print(f"    {leg['leg_id']:<10} technical finality: {f['technical_model']}{depth}"
              f"   legal: {f['legal']['regime_ref']}")

    step("A.5", "Settlement interface (Committed) — the revocability boundary")
    print(f"    state: {coord.commit(sid)}")
    print("    Coordinator holds both legs' states: enqueued, will not be lost, no longer")
    print("    revocable by a participant. Both rulebooks anchor legal finality here —")
    print("    but they disagree downstream:")
    for leg in legs:
        lg = leg["finality"]["legal"]
        print(f"      {leg['leg_id']:<10} abort_after_committed = {lg['abort_after_committed']}"
              f"   ({lg['regime_ref']})")
    print("    An open question this surfaces: when two rulebooks disagree, does the")
    print("    instruction take the stricter one, or must the pair be rejected at proposal?")

    step("A.6", "Settlement interface (Settled)")
    print(f"    state: {coord.settle(sid)}")
    print(f"    bond: fund-b holds {evm.tokens['BOND31'].balances.get('fund-b', 0):,} units")
    print(f"    cash: bank-a-dealer holds {sui.balance('bank-a-dealer'):,} deposit units "
          f"in PAS account {sui._account('bank-a-dealer').object_id}")
    print("    Receiver eligibility is re-checked at claim time, so a revocation between")
    print("    Committed and Settled still cannot take delivery.")

    # ---------------------------- Scenario B ----------------------------
    banner("Scenario B — the buyer's sanctions credential is revoked mid-day (Flow C)")
    oracle.revoke("fund-b", "SANCTIONS_CLEAR")
    legs_b = make_legs(evm, sui, 50_000, 1_250_000)
    sid_b = coord.propose(legs_b)
    step("B.1", "The pre-settlement check now denies on both rails")
    for leg_id, code in coord.presettlement_check(sid_b).items():
        print(f"    {leg_id:<10} {code}")
    print("    On EVM the registry check fails; on Sui the IssuerComplianceWitness simply")
    print("    withholds its stamp, so the request cannot collect the approvals Policy<T>")
    print("    names and never resolves. Different mechanisms, one reason code, nothing locks.")
    for topic in ("KYC_COMPLETE", "SANCTIONS_CLEAR"):
        oracle.present("fund-b", topic, "did:web:kyc.fund-b.example",
                       {"subject": "fund-b", "topic": topic, "assurance": "high", "reissued": True})

    # ---------------------------- Scenario C ----------------------------
    banner("Scenario C — the cash leg's state is not held before timeout")
    legs_c = make_legs(evm, sui, 25_000, 625_000)
    sid_c = coord.propose(legs_c)
    coord.presettlement_check(sid_c)
    step("C.1", "Commit attempted; one leg never confirms")
    print(f"    state: {coord.commit(sid_c, fail_leg='leg-cash')}")
    print(f"    dealer's bond balance restored: "
          f"{evm.tokens['BOND31'].balances['bank-a-dealer']:,} units")
    print("    Nothing settles alone: principal risk is removed by construction.")

    # -------------------------- Reconciliation --------------------------
    banner("Canonical events — one indexer reconciles both rails")
    report = reconcile({"evm": evm.events, "sui": sui.events})
    print(f"  canonical events: {report['total_events']}   "
          f"schema violations: {report['schema_errors']}")
    for sid_, s in report["settlements"].items():
        print(f"  {sid_}: rails={s['rails']}  outcome={s['outcome']}  "
              f"atomicity_ok={s['atomicity_ok']}")
        if s.get("finality_models"):
            print(f"      declared finality: {', '.join(sorted(s['finality_models']))}")
    out = ROOT / "demo" / "event_log.json"
    out.write_text(json.dumps({"evm": evm.events, "sui": sui.events}, indent=2))
    print(f"\n  cross-rail event log written to {out.name}")
    print("\n  Note the reconciler reports the DECLARED finality model per rail rather than")
    print("  inferring it: one leg is deterministic, the other probabilistic, and an event")
    print("  having been emitted says nothing by itself about either.")


if __name__ == "__main__":
    main()
