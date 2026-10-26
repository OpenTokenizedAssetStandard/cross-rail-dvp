// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {OTASReasons, OTASDenied} from "./OTASReasons.sol";

interface IOTASRestrictedToken {
    function otasCanTransfer(address from, address to, uint256 amount) external view returns (uint16);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
    function returnFromEscrow(address to, uint256 amount) external;
}

/// AtomicLeg binding for the EVM rail: a hash-time-locked escrow for an OTAS
/// restricted token.
///
/// The hashlock is SHA-256 of the preimage, because Sui exposes the same function
/// (std::hash::sha2_256) -- one secret opens both legs. `claim` is permissionless:
/// funds can only go to the receiver fixed at lock time, so whoever submits the
/// claim can trigger delivery but cannot redirect it. Receiver eligibility is
/// re-checked at claim time; `refund` returns units to the original sender after
/// the timelock.
///
/// Research and educational reference per the OTAS Lab charter. Not audited.
contract OTASHTLC {
    enum State {
        None,
        Open,
        Claimed,
        Refunded
    }

    struct Lock {
        address token;
        address sender;
        address receiver;
        uint256 amount;
        bytes32 hashlock;
        uint64 timelock;
        State state;
        bytes32 settlementId;
        bytes32 legId;
    }

    mapping(bytes32 => Lock) public locks;

    event Locked(
        bytes32 indexed lockId,
        bytes32 indexed settlementId,
        bytes32 legId,
        address sender,
        address receiver,
        address token,
        uint256 amount,
        bytes32 hashlock,
        uint64 timelock
    );
    event Claimed(bytes32 indexed lockId, bytes32 indexed settlementId, bytes preimage);
    event Refunded(bytes32 indexed lockId, bytes32 indexed settlementId);

    error LockExists();
    error NotOpen();
    error TimelockInPast();
    error Expired();
    error NotExpired();
    error BadPreimage();
    error TransferFailed();

    function lockId(bytes32 settlementId, bytes32 legId) public pure returns (bytes32) {
        return keccak256(abi.encode(settlementId, legId));
    }

    function lock(
        address token,
        address receiver,
        uint256 amount,
        bytes32 hashlock,
        uint64 timelock,
        bytes32 settlementId,
        bytes32 legId
    ) external returns (bytes32 id) {
        id = lockId(settlementId, legId);
        if (locks[id].state != State.None) revert LockExists();
        if (timelock <= block.timestamp) revert TimelockInPast();

        // The leg is only locked if the eventual delivery would be allowed now.
        uint16 code = IOTASRestrictedToken(token).otasCanTransfer(msg.sender, receiver, amount);
        if (code != OTASReasons.OTAS_OK) revert OTASDenied(code);

        locks[id] = Lock(token, msg.sender, receiver, amount, hashlock, timelock, State.Open, settlementId, legId);
        if (!IOTASRestrictedToken(token).transferFrom(msg.sender, address(this), amount)) revert TransferFailed();
        emit Locked(id, settlementId, legId, msg.sender, receiver, token, amount, hashlock, timelock);
    }

    function claim(bytes32 id, bytes calldata preimage) external {
        Lock storage lk = locks[id];
        if (lk.state != State.Open) revert NotOpen();
        if (block.timestamp >= lk.timelock) revert Expired();
        if (sha256(preimage) != lk.hashlock) revert BadPreimage();

        // Claim-time re-check: eligibility lost between Committed and Settled
        // still cannot take delivery. The units stay put and refund after timeout.
        uint16 code = IOTASRestrictedToken(lk.token).otasCanTransfer(address(this), lk.receiver, lk.amount);
        if (code != OTASReasons.OTAS_OK) revert OTASDenied(code);

        lk.state = State.Claimed;
        if (!IOTASRestrictedToken(lk.token).transfer(lk.receiver, lk.amount)) revert TransferFailed();
        emit Claimed(id, lk.settlementId, preimage);
    }

    function refund(bytes32 id) external {
        Lock storage lk = locks[id];
        if (lk.state != State.Open) revert NotOpen();
        if (block.timestamp < lk.timelock) revert NotExpired();
        lk.state = State.Refunded;
        IOTASRestrictedToken(lk.token).returnFromEscrow(lk.sender, lk.amount);
        emit Refunded(id, lk.settlementId);
    }
}
