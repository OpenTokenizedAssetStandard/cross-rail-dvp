"""OTAS rail adapters.

One adapter interface, two genuinely different accounting models underneath:
  - EVMRail  : account/balance state; compliance via external registries +
               modular compliance contracts (the ERC-3643 placement)
  - SuiRail  : Sui Permissioned Asset Standard (PAS). Ownership sits in shared
               Account objects; each managed asset type carries a Policy<T>
               declaring which approval witnesses each action requires; every
               state change follows create -> approve -> resolve, and the
               request is a hot potato that must resolve in the same
               transaction or the transaction aborts.

These are the simulated counterparts of the contracts in live/ (live/evm and
live/sui/otas_live), which enforce the same reason codes on real chains.
Illustrative research prototypes per the OTAS Lab charter, not products.

Note on PAS and OTAS: PAS deliberately does not decide policy. It standardizes
the approval-gating mechanism and leaves eligibility logic to the issuer's
approval-witness code. That is exactly the seam OTAS names: the issuer's witness
module is where `canTransfer` semantics bind on this rail, and it is the witness
that refuses to stamp -- carrying an OTAS reason code -- when eligibility fails.
"""
from __future__ import annotations
import hashlib, itertools, time, uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

_ids = itertools.count(1)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_event(event_type, token_ref, rail, payload, settlement_id=None,
              finality_model="deterministic", legal=None):
    """Canonical event envelope. `finality` declares the rail's technical
    finality MODEL; where a settlement lifecycle event carries legal finality,
    it also declares the MOMENT the governing rulebook anchors."""
    ev = {
        "spec_version": "1.0.0",
        "event_type": event_type,
        "event_id": f"ev-{next(_ids):04d}",
        "token_ref": token_ref,
        "rail": rail,
        "tx_ref": "0x" + hashlib.sha256(f"{event_type}{next(_ids)}".encode()).hexdigest()[:16],
        "ts": now(),
        "payload": payload,
    }
    if settlement_id:
        ev["settlement_id"] = settlement_id
    fin = {"technical_model": finality_model}
    if legal:
        fin["legal"] = legal
    ev["finality"] = fin
    return ev


class RailAdapter(ABC):
    """The seam the standard defines: express and verify, not execute."""

    def __init__(self, name, eligibility_oracle):
        self.name = name
        self.oracle = eligibility_oracle
        self.events: list[dict] = []

    @abstractmethod
    def can_transfer(self, token, frm, to, amount) -> str: ...
    @abstractmethod
    def lock_leg(self, token, frm, amount, hashlock, timeout, settlement_id) -> str: ...
    @abstractmethod
    def claim_leg(self, lock_ref, secret, to, settlement_id) -> bool: ...
    @abstractmethod
    def refund_leg(self, lock_ref, settlement_id) -> bool: ...

    def emit(self, ev):
        self.events.append(ev)
        return ev


# =========================== EVM: account/balance ===========================

@dataclass
class EVMToken:
    symbol: str
    token_ref: dict
    balances: dict = field(default_factory=dict)
    frozen: set = field(default_factory=set)
    paused: bool = False
    holder_cap: int = 2000


class EVMRail(RailAdapter):
    """Account/balance model. Compliance lives in registries external to the
    token plus modular compliance rules, consulted at transfer (ERC-3643)."""

    FINALITY_MODEL = "probabilistic"  # public EVM: reorg risk decaying with depth

    def __init__(self, oracle):
        super().__init__("evm-account", oracle)
        self.tokens: dict[str, EVMToken] = {}
        self.locks: dict[str, dict] = {}

    def deploy(self, symbol, token_ref, issuance: dict):
        t = EVMToken(symbol, token_ref, dict(issuance))
        self.tokens[symbol] = t
        for holder, amt in issuance.items():
            self.emit(new_event("Issued", token_ref, self.name, {"to": holder, "amount": amt},
                                finality_model=self.FINALITY_MODEL))
        return t

    def can_transfer(self, token, frm, to, amount):
        """OTAS canTransfer convention, bound here to the ERC-3643 mechanism."""
        t = self.tokens[token]
        if t.paused:
            return "PAUSED"
        if frm in t.frozen or to in t.frozen:
            return "FROZEN_ACCOUNT"
        if not self.oracle.is_eligible(frm):
            return "INELIGIBLE_SENDER"
        if not self.oracle.is_eligible(to):
            return self.oracle.deny_code(to) or "INELIGIBLE_RECEIVER"
        if t.balances.get(frm, 0) < amount:
            return "SUPPLY_RULE_VIOLATION"
        holders = {a for a, b in t.balances.items() if b > 0}
        if to not in holders and len(holders) >= t.holder_cap:
            return "HOLDER_CAP_EXCEEDED"
        return "OTAS_OK"

    def lock_leg(self, token, frm, amount, hashlock, timeout, settlement_id):
        code = self.can_transfer(token, frm, "ESCROW", amount)
        if code not in ("OTAS_OK", "INELIGIBLE_RECEIVER"):  # escrow is a system address
            raise RuntimeError(f"lock refused: {code}")
        t = self.tokens[token]
        t.balances[frm] -= amount
        ref = f"evm-lock-{uuid.uuid4().hex[:8]}"
        self.locks[ref] = {"token": token, "frm": frm, "amount": amount,
                           "hashlock": hashlock, "timeout": timeout, "open": True}
        return ref

    def claim_leg(self, lock_ref, secret, to, settlement_id):
        lk = self.locks[lock_ref]
        if not lk["open"] or hashlib.sha256(secret.encode()).hexdigest() != lk["hashlock"]:
            return False
        # Receiver-side re-check at claim: eligibility lapsing between Committed
        # and Settled must not permit delivery.
        code = self.can_transfer(lk["token"], "ESCROW", to, 0)
        if code not in ("OTAS_OK", "INELIGIBLE_SENDER"):
            return False
        t = self.tokens[lk["token"]]
        t.balances[to] = t.balances.get(to, 0) + lk["amount"]
        lk["open"] = False
        self.emit(new_event("Transferred", t.token_ref, self.name,
                            {"from": lk["frm"], "to": to, "amount": lk["amount"], "via": "htlc-claim"},
                            settlement_id=settlement_id, finality_model=self.FINALITY_MODEL))
        return True

    def refund_leg(self, lock_ref, settlement_id):
        lk = self.locks[lock_ref]
        if not lk["open"]:
            return False
        self.tokens[lk["token"]].balances[lk["frm"]] += lk["amount"]
        lk["open"] = False
        return True

    def forced_transfer(self, token, frm, to, amount):
        """ForceTransferable: agent-gated seizure (ERC-3643 forced transfer)."""
        t = self.tokens[token]
        t.balances[frm] -= amount
        t.balances[to] = t.balances.get(to, 0) + amount
        self.emit(new_event("ForcedTransfer", t.token_ref, self.name,
                            {"from": frm, "to": to, "amount": amount, "authority": "agent"},
                            finality_model=self.FINALITY_MODEL))


# ====================== Sui: Permissioned Asset Standard ======================

class ApprovalRefused(RuntimeError):
    """An approval witness declined to stamp. The request cannot resolve; the
    hot potato is unresolved, so the whole transaction aborts."""

    def __init__(self, code):
        super().__init__(f"required approval not collected: {code}")
        self.code = code


@dataclass
class PASAccount:
    """Shared Account object, one per address, deterministically derived from
    the system Namespace. Funds accrue as address balances per coin type."""
    object_id: str
    owner: str
    balances: dict = field(default_factory=dict)


@dataclass
class PASRequest:
    """Hot potato: Request<SendFunds<T>> / <ClawbackFunds<T>> / <UnlockFunds<T>>.
    Resolves only when the collected witnesses, matched by TypeName, are exactly
    those the Policy names for that action."""
    action: str
    coin_type: str
    frm: str
    to: str
    amount: int
    collected: set = field(default_factory=set)
    resolved: bool = False

    def approve(self, witness_type: str):
        self.collected.add(witness_type)
        return self


class SuiRail(RailAdapter):
    """Sui PAS. A managed asset cannot leave the system except through a request
    with matching approvals; enabling `unlock_funds` is the escape hatch that
    voids all future transfer control, so this policy leaves it disabled."""

    FINALITY_MODEL = "deterministic"  # Sui: single-block deterministic finality

    # Policy<T>: which approval witnesses each action requires.
    POLICY = {
        "send_funds": ["IssuerComplianceWitness"],
        "clawback_funds": ["IssuerComplianceWitness"],
        # unlock_funds intentionally absent: enabling it would void transfer control.
    }

    def __init__(self, oracle):
        super().__init__("sui-object", oracle)
        self.accounts: dict[str, PASAccount] = {}
        self.deny_list: set = set()
        self.global_pause = False
        self.escrows: dict[str, dict] = {}
        self.token_ref = None
        self.coin_type = None

    # -- account plumbing (Accounts are created permissionlessly) --

    def _account(self, owner) -> PASAccount:
        if owner not in self.accounts:
            self.accounts[owner] = PASAccount(f"0xacct{uuid.uuid4().hex[:10]}", owner)
        return self.accounts[owner]

    def publish(self, token_ref, issuance: dict):
        self.token_ref = token_ref
        self.coin_type = token_ref["asset_id"]
        for owner, amt in issuance.items():
            acct = self._account(owner)
            acct.balances[self.coin_type] = acct.balances.get(self.coin_type, 0) + amt
            self.emit(new_event("Issued", token_ref, self.name,
                                {"to": owner, "amount": amt, "account": acct.object_id},
                                finality_model=self.FINALITY_MODEL))

    # -- the issuer's approval-witness module: where OTAS eligibility binds --

    def _issuer_compliance_witness(self, action, frm, to) -> str:
        """Returns OTAS_OK if this package would stamp the request, else the
        OTAS reason code explaining why it refuses. PAS gates the action; the
        eligibility logic is the issuer's, and its verdict is what OTAS
        standardizes into a common result vocabulary."""
        if self.global_pause:
            return "PAUSED"
        if frm in self.deny_list or to in self.deny_list:
            return "FROZEN_ACCOUNT"
        for party in (frm, to):
            if party in ("ESCROW", None):
                continue  # escrow is a policy-recognized system account
            if not self.oracle.is_eligible(party):
                return self.oracle.deny_code(party) or (
                    "INELIGIBLE_SENDER" if party == frm else "INELIGIBLE_RECEIVER")
        return "OTAS_OK"

    def _create_approve_resolve(self, action, frm, to, amount):
        """The PAS lifecycle. Raises ApprovalRefused if a required witness
        declines, which leaves the hot potato unresolved."""
        req = PASRequest(action, self.coin_type, frm, to, amount)
        required = self.POLICY.get(action)
        if required is None:
            raise ApprovalRefused("UNSPECIFIED_DENY")  # action not enabled by policy
        for witness in required:
            if witness == "IssuerComplianceWitness":
                code = self._issuer_compliance_witness(action, frm, to)
                if code != "OTAS_OK":
                    raise ApprovalRefused(code)
            req.approve(witness)
        if req.collected != set(required):  # exact TypeName match, per PAS
            raise ApprovalRefused("UNSPECIFIED_DENY")
        req.resolved = True
        return req

    # -- OTAS interface --

    def can_transfer(self, token, frm, to, amount):
        """OTAS canTransfer convention, bound here to PAS: would a
        Request<SendFunds<T>> collect exactly the approvals Policy<T> names?"""
        code = self._issuer_compliance_witness("send_funds", frm, to)
        if code != "OTAS_OK":
            return code
        if self.balance(frm) < amount:
            return "SUPPLY_RULE_VIOLATION"
        return "OTAS_OK"

    def lock_leg(self, token, frm, amount, hashlock, timeout, settlement_id):
        if self.balance(frm) < amount:
            raise RuntimeError("insufficient balance")
        try:
            self._create_approve_resolve("send_funds", frm, "ESCROW", amount)
        except ApprovalRefused as e:
            raise RuntimeError(f"PAS request unresolved: {e.code}") from None
        src = self._account(frm)
        esc = self._account("ESCROW")
        src.balances[self.coin_type] -= amount
        esc.balances[self.coin_type] = esc.balances.get(self.coin_type, 0) + amount
        ref = f"sui-escrow-{uuid.uuid4().hex[:8]}"
        self.escrows[ref] = {"frm": frm, "amount": amount, "hashlock": hashlock,
                             "timeout": timeout, "open": True}
        return ref

    def claim_leg(self, lock_ref, secret, to, settlement_id):
        es = self.escrows[lock_ref]
        if not es["open"] or hashlib.sha256(secret.encode()).hexdigest() != es["hashlock"]:
            return False
        # Release is itself a send_funds request, so the receiver is re-approved
        # at claim time as a consequence of PAS -- not as a bolted-on check.
        try:
            self._create_approve_resolve("send_funds", "ESCROW", to, es["amount"])
        except ApprovalRefused:
            return False
        esc = self._account("ESCROW")
        dst = self._account(to)
        esc.balances[self.coin_type] -= es["amount"]
        dst.balances[self.coin_type] = dst.balances.get(self.coin_type, 0) + es["amount"]
        es["open"] = False
        self.emit(new_event("Transferred", self.token_ref, self.name,
                            {"from": es["frm"], "to": to, "amount": es["amount"],
                             "account": dst.object_id, "via": "pas-send_funds"},
                            settlement_id=settlement_id, finality_model=self.FINALITY_MODEL))
        return True

    def refund_leg(self, lock_ref, settlement_id):
        es = self.escrows[lock_ref]
        if not es["open"]:
            return False
        esc = self._account("ESCROW")
        dst = self._account(es["frm"])
        esc.balances[self.coin_type] -= es["amount"]
        dst.balances[self.coin_type] = dst.balances.get(self.coin_type, 0) + es["amount"]
        es["open"] = False
        return True

    def clawback(self, frm, to, amount):
        """ForceTransferable bound to PAS clawback_funds: a native seizure path
        gated by the same Policy<T>."""
        self._create_approve_resolve("clawback_funds", frm, to, amount)
        self._account(frm).balances[self.coin_type] -= amount
        dst = self._account(to)
        dst.balances[self.coin_type] = dst.balances.get(self.coin_type, 0) + amount
        self.emit(new_event("ForcedTransfer", self.token_ref, self.name,
                            {"from": frm, "to": to, "amount": amount,
                             "authority": "policy-approved clawback_funds"},
                            finality_model=self.FINALITY_MODEL))

    def balance(self, owner):
        return self._account(owner).balances.get(self.coin_type, 0)
