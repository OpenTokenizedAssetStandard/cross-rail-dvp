"""otas-identity: eligibility verification seam.

Profile over W3C VC semantics: Issuer -> Holder -> Verifier. The standard carries
credential HASHES and boolean/proof results only — never credential contents, never PII.
A revocation flips the verification result; the token's Restricted behavior does the rest.
"""
import hashlib, json, time

CLAIM_TOPICS = ["KYC_COMPLETE", "JURISDICTION", "INVESTOR_CLASS", "SANCTIONS_CLEAR"]


class TrustedIssuerList:
    def __init__(self, issuers):
        self.issuers = set(issuers)

    def trusted(self, did):
        return did in self.issuers


class EligibilityOracle:
    """isEligible(party, claim_topics) -> bool, plus a coarse deny code.
    Presentations are stored as (topic -> {issuer_did, claim_hash, revoked})."""

    def __init__(self, trust_list: TrustedIssuerList, required=("KYC_COMPLETE", "SANCTIONS_CLEAR")):
        self.trust_list = trust_list
        self.required = required
        self.presentations = {}
        self.audit = []

    def present(self, party, topic, issuer_did, claim_payload: dict):
        # Only the hash of the (off-chain) credential ever enters this layer.
        claim_hash = hashlib.sha256(json.dumps(claim_payload, sort_keys=True).encode()).hexdigest()
        self.presentations.setdefault(party, {})[topic] = {
            "issuer_did": issuer_did, "claim_hash": claim_hash, "revoked": False}

    def revoke(self, party, topic):
        if topic in self.presentations.get(party, {}):
            self.presentations[party][topic]["revoked"] = True

    def is_eligible(self, party, claim_topics=None):
        topics = claim_topics or self.required
        creds = self.presentations.get(party, {})
        ok = all(
            t in creds and not creds[t]["revoked"] and self.trust_list.trusted(creds[t]["issuer_did"])
            for t in topics
        )
        self.audit.append({"party_hash": hashlib.sha256(party.encode()).hexdigest()[:12],
                           "topics": list(topics), "result": ok,
                           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return ok

    def deny_code(self, party):
        creds = self.presentations.get(party, {})
        sc = creds.get("SANCTIONS_CLEAR")
        if sc and sc["revoked"]:
            return "SANCTIONS_HIT"
        return None
