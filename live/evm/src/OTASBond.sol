// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {OTASReasons, OTASDenied} from "./OTASReasons.sol";
import {OTASIdentityRegistry} from "./OTASIdentityRegistry.sol";

/// A tokenized sovereign bond on the EVM rail: FractionalUniqueBase with
/// Restricted, Freezable (via registry), ForceTransferable and AtomicLeg behaviours.
///
/// ERC-20 compatible. Compliance is the ERC-3643 placement: an external identity
/// registry consulted on every movement. `otasCanTransfer` is the OTAS interface
/// convention bound to that mechanism, it is not the ERC-3643 function of a
/// similar name, and it returns OTAS reason codes rather than a bool.
///
/// Research and educational reference per the OTAS Lab charter. Not audited.
contract OTASBond {
    string public name;
    string public symbol;
    uint8 public constant decimals = 0;
    uint256 public totalSupply;

    OTASIdentityRegistry public immutable registry;
    address public agent;
    /// Content hash of the off-chain capability manifest (OTAS 5.2 discovery).
    bytes32 public manifestHash;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(
        address indexed owner,
        address indexed spender,
        uint256 value
    );
    event EligibilityChecked(
        address indexed from,
        address indexed to,
        uint16 reasonCode
    );
    event ForcedTransfer(
        address indexed from,
        address indexed to,
        uint256 value
    );
    event MetadataAnchored(bytes32 hash);

    error NotAgent();
    error NotSystemAccount();
    error InsufficientAllowance();

    modifier onlyAgent() {
        if (msg.sender != agent) revert NotAgent();
        _;
    }

    constructor(
        string memory name_,
        string memory symbol_,
        OTASIdentityRegistry registry_,
        bytes32 manifestHash_
    ) {
        name = name_;
        symbol = symbol_;
        registry = registry_;
        agent = msg.sender;
        manifestHash = manifestHash_;
        emit MetadataAnchored(manifestHash_);
    }

    /// OTAS compliance interface: allow (0) or deny with a reason code.
    /// A pre-settlement check -- callable as a free view before anything locks.
    function otasCanTransfer(
        address from,
        address to,
        uint256 amount
    ) public view returns (uint16) {
        uint16 code = registry.check(from, to);
        if (code != OTASReasons.OTAS_OK) return code;
        if (balanceOf[from] < amount) return OTASReasons.SUPPLY_RULE_VIOLATION;
        return OTASReasons.OTAS_OK;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _checkedMove(msg.sender, to, amount);
        return true;
    }

    function transferFrom(
        address from,
        address to,
        uint256 amount
    ) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed < amount) revert InsufficientAllowance();
        if (allowed != type(uint256).max)
            allowance[from][msg.sender] = allowed - amount;
        _checkedMove(from, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    // ---- issuer / agent controls -------------------------------------------------

    function issue(address to, uint256 amount) external onlyAgent {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function forcedTransfer(
        address from,
        address to,
        uint256 amount
    ) external onlyAgent {
        _move(from, to, amount);
        emit ForcedTransfer(from, to, amount);
    }

    /// A settlement escrow returning a sender's own units (HTLC refund). Skips the
    /// eligibility check deliberately: a sender whose credential lapsed while their
    /// units sat in escrow must still get them back, not have them stranded.
    function returnFromEscrow(address to, uint256 amount) external {
        if (!registry.systemAccount(msg.sender)) revert NotSystemAccount();
        _move(msg.sender, to, amount);
    }

    // ---- internals ---------------------------------------------------------------

    function _checkedMove(address from, address to, uint256 amount) internal {
        uint16 code = otasCanTransfer(from, to, amount);
        if (code != OTASReasons.OTAS_OK) revert OTASDenied(code);
        emit EligibilityChecked(from, to, code);
        _move(from, to, amount);
    }

    function _move(address from, address to, uint256 amount) internal {
        uint256 bal = balanceOf[from];
        if (bal < amount) revert OTASDenied(OTASReasons.SUPPLY_RULE_VIOLATION);
        unchecked {
            balanceOf[from] = bal - amount;
        }
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
