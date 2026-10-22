"""otas-settle: reference settlement coordinator.

Lifecycle (whitepaper 6.1): PROPOSED -> COMMITTED -> SETTLED | ABORTED

Once the coordinator holds both legs' states the instruction moves to COMMITTED:
it is enqueued, will not be lost, and can no longer be revoked by a participant.
That transition is the revocability boundary and the natural place for a
rulebook to anchor legal finality; SETTLED marks final settlement.

Two things are declared per leg rather than inferred from atomicity:
  (1) the rail's TECHNICAL FINALITY MODEL -- deterministic or probabilistic --
      since a settled-looking transfer on a probabilistic rail carries residual
      reorganization risk that decays with depth; and
  (2) the LEGAL FINALITY construct: the governing rulebook, which moment it
      anchors, and whether it permits Abort after Committed.

OTAS provides the construct to express which moment governs under which model.
The legal determination itself remains the operator's and the jurisdiction's
responsibility, so this coordinator requires the declaration and never supplies it.
"""
import hashlib, secrets, uuid
from .rails import new_event


class SettlementCoordinator:
    def __init__(self):
        self.instructions = {}

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _leg_finality(leg):
        """The leg's declared finality block, as it appears in events."""
        fin = leg["finality"]
        return fin["technical_model"], dict(fin["legal"])

    # -- lifecycle -----------------------------------------------------------

    def propose(self, legs, kind="DvP", mechanism="htlc"):
        secret = secrets.token_hex(16)
        instr = {
            "spec_version": "1.0.0",
            "settlement_id": f"stl-{uuid.uuid4().hex[:10]}",
            "kind": kind,
            "state": "PROPOSED",
            "mechanism": {"type": mechanism,
                          "hashlock": hashlib.sha256(secret.encode()).hexdigest(),
                          "timeout_policy": {"asset_leg_s": 7200, "cash_leg_s": 3600}},
            "legs": legs,
        }
        self.instructions[instr["settlement_id"]] = {"instr": instr, "secret": secret, "locks": {}}
        for leg in legs:
            model, legal = self._leg_finality(leg)
            leg["rail_obj"].emit(new_event(
                "SettlementProposed", leg["token_ref"], leg["rail_obj"].name,
                {"leg_id": leg["leg_id"], "role": leg["role"], "amount": leg["amount"],
                 "settlement_asset_tier": leg.get("settlement_asset_tier", "not-cash"),
                 "mechanism": mechanism},
                settlement_id=instr["settlement_id"], finality_model=model, legal=legal))
        return instr["settlement_id"]

    def presettlement_check(self, settlement_id):
        """OTAS canTransfer on every leg, before a settlement instruction is
        acted on: any blocking condition is knowable in advance."""
        rec = self.instructions[settlement_id]
        results = {}
        for leg in rec["instr"]["legs"]:
            code = leg["rail_obj"].can_transfer(leg["token"], leg["from"], leg["to"], leg["amount"])
            results[leg["leg_id"]] = code
            model, _ = self._leg_finality(leg)
            leg["rail_obj"].emit(new_event(
                "EligibilityChecked", leg["token_ref"], leg["rail_obj"].name,
                {"result": code == "OTAS_OK", "reason_code": code, "leg_id": leg["leg_id"]},
                settlement_id=settlement_id, finality_model=model))
        return results

    def commit(self, settlement_id, fail_leg=None):
        rec = self.instructions[settlement_id]
        instr = rec["instr"]
        hashlock = instr["mechanism"]["hashlock"]
        for leg in instr["legs"]:
            if not leg.get("finality", {}).get("legal", {}).get("regime_ref"):
                return self._abort(settlement_id, "leg has no declared legal-finality construct")
            if fail_leg == leg["leg_id"]:
                return self._abort(settlement_id, f"leg {fail_leg} state not held before timeout")
            try:
                ref = leg["rail_obj"].lock_leg(leg["token"], leg["from"], leg["amount"],
                                               hashlock, 0, settlement_id)
            except RuntimeError as e:
                return self._abort(settlement_id, str(e))
            rec["locks"][leg["leg_id"]] = ref
            leg["lock_ref"] = ref

        instr["state"] = "COMMITTED"
        for leg in instr["legs"]:
            model, legal = self._leg_finality(leg)
            leg["rail_obj"].emit(new_event(
                "Committed", leg["token_ref"], leg["rail_obj"].name,
                {"leg_id": leg["leg_id"], "lock_ref": leg["lock_ref"],
                 "note": "coordinator holds both legs' states; enqueued and no longer "
                         "revocable by a participant"},
                settlement_id=settlement_id, finality_model=model, legal=legal))
        return "COMMITTED"

    def settle(self, settlement_id):
        rec = self.instructions[settlement_id]
        instr = rec["instr"]
        if instr["state"] != "COMMITTED":
            raise RuntimeError("cannot settle: instruction is not Committed")
        for leg in instr["legs"]:
            ok = leg["rail_obj"].claim_leg(leg["lock_ref"], rec["secret"], leg["to"], settlement_id)
            if not ok:
                raise RuntimeError("claim failed after Committed — mechanism invariant violated")
        instr["state"] = "SETTLED"
        for leg in instr["legs"]:
            model, legal = self._leg_finality(leg)
            leg["rail_obj"].emit(new_event(
                "Settled", leg["token_ref"], leg["rail_obj"].name,
                {"leg_id": leg["leg_id"]}, settlement_id=settlement_id,
                finality_model=model, legal=legal))
        return "SETTLED"

    def _abort(self, settlement_id, reason):
        rec = self.instructions[settlement_id]
        instr = rec["instr"]
        for leg in instr["legs"]:
            ref = rec["locks"].get(leg["leg_id"])
            if ref:
                leg["rail_obj"].refund_leg(ref, settlement_id)
            model, _ = self._leg_finality(leg)
            leg["rail_obj"].emit(new_event(
                "Aborted", leg["token_ref"], leg["rail_obj"].name,
                {"leg_id": leg["leg_id"], "reason": reason},
                settlement_id=settlement_id, finality_model=model))
        instr["state"] = "ABORTED"
        return "ABORTED"
