// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {OTASReasons} from "./OTASReasons.sol";

/// Eligibility registry for the EVM rail, in the ERC-3643 placement: an external
/// registry the token consults at transfer time.
///
/// Holds credential HASHES and a revoked flag per claim topic -- never the
/// credential itself and never personal data. The same 32-byte hash of an
/// off-chain verifiable credential is registered on both rails.
contract OTASIdentityRegistry {
    bytes32 public constant KYC_COMPLETE = keccak256("KYC_COMPLETE");
    bytes32 public constant SANCTIONS_CLEAR = keccak256("SANCTIONS_CLEAR");

    struct Claim {
        bytes32 claimHash;
        bool present;
        bool revoked;
    }

    address public admin;
    bool public paused;
    mapping(address => mapping(bytes32 => Claim)) public claims;
    mapping(address => bool) public frozen;
    /// Settlement escrows: recognised by policy, so they may hold restricted units.
    mapping(address => bool) public systemAccount;

    event ClaimSet(address indexed party, bytes32 indexed topic, bytes32 claimHash);
    event ClaimRevoked(address indexed party, bytes32 indexed topic);
    event FrozenSet(address indexed party, bool frozen);
    event PausedSet(bool paused);
    event SystemAccountSet(address indexed account, bool enabled);

    error NotAdmin();
    error LengthMismatch();

    modifier onlyAdmin() {
        if (msg.sender != admin) revert NotAdmin();
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    function setClaim(address party, bytes32 topic, bytes32 claimHash) public onlyAdmin {
        claims[party][topic] = Claim(claimHash, true, false);
        emit ClaimSet(party, topic, claimHash);
    }

    function setClaims(address[] calldata parties, bytes32[] calldata topics, bytes32[] calldata hashes)
        external
        onlyAdmin
    {
        if (parties.length != topics.length || topics.length != hashes.length) revert LengthMismatch();
        for (uint256 i = 0; i < parties.length; i++) {
            setClaim(parties[i], topics[i], hashes[i]);
        }
    }

    function revokeClaim(address party, bytes32 topic) external onlyAdmin {
        claims[party][topic].revoked = true;
        emit ClaimRevoked(party, topic);
    }

    function setFrozen(address party, bool isFrozen) external onlyAdmin {
        frozen[party] = isFrozen;
        emit FrozenSet(party, isFrozen);
    }

    function setPaused(bool isPaused) external onlyAdmin {
        paused = isPaused;
        emit PausedSet(isPaused);
    }

    function setSystemAccount(address account, bool enabled) external onlyAdmin {
        systemAccount[account] = enabled;
        emit SystemAccountSet(account, enabled);
    }

    function isEligible(address party) public view returns (bool) {
        Claim memory k = claims[party][KYC_COMPLETE];
        Claim memory s = claims[party][SANCTIONS_CLEAR];
        return k.present && !k.revoked && s.present && !s.revoked;
    }

    /// The OTAS compliance verdict for a movement from `from` to `to`, as a reason code.
    /// Order: paused, frozen, sender, receiver -- identical to the Sui rail's witness.
    function check(address from, address to) public view returns (uint16) {
        if (paused) return OTASReasons.PAUSED;
        if (frozen[from] || frozen[to]) return OTASReasons.FROZEN_ACCOUNT;
        if (!systemAccount[from]) {
            uint16 c = _partyCode(from, OTASReasons.INELIGIBLE_SENDER);
            if (c != OTASReasons.OTAS_OK) return c;
        }
        if (!systemAccount[to]) {
            uint16 c = _partyCode(to, OTASReasons.INELIGIBLE_RECEIVER);
            if (c != OTASReasons.OTAS_OK) return c;
        }
        return OTASReasons.OTAS_OK;
    }

    function _partyCode(address party, uint16 ineligibleCode) internal view returns (uint16) {
        Claim memory s = claims[party][SANCTIONS_CLEAR];
        // Coarse on purpose: the wire says SANCTIONS_HIT, never which list or rule.
        if (s.present && s.revoked) return OTASReasons.SANCTIONS_HIT;
        if (!isEligible(party)) return ineligibleCode;
        return OTASReasons.OTAS_OK;
    }
}
