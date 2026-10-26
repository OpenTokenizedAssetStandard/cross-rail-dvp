// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {OTASIdentityRegistry} from "../src/OTASIdentityRegistry.sol";
import {OTASBond} from "../src/OTASBond.sol";
import {OTASHTLC} from "../src/OTASHTLC.sol";
import {OTASDenied} from "../src/OTASReasons.sol";

contract OTASTest is Test {
    OTASIdentityRegistry reg;
    OTASBond bond;
    OTASHTLC htlc;

    address dealer = makeAddr("dealer");
    address fund = makeAddr("fund");
    address stranger = makeAddr("stranger");

    bytes preimage = hex"6f74617320736563726574206f74617320736563726574206f74617320736563";
    bytes32 hashlock;
    bytes32 constant SID = keccak256("stl-1");
    bytes32 constant LEG = keccak256("leg-asset");

    function setUp() public {
        reg = new OTASIdentityRegistry();
        bond = new OTASBond("Tokenized Sovereign Bond 2031", "TSB31", reg, keccak256("manifest"));
        htlc = new OTASHTLC();
        reg.setSystemAccount(address(htlc), true);
        _eligible(dealer);
        _eligible(fund);
        bond.issue(dealer, 1_000_000);
        hashlock = sha256(preimage);
    }

    function _eligible(address p) internal {
        reg.setClaim(p, reg.KYC_COMPLETE(), keccak256(abi.encode(p, "kyc")));
        reg.setClaim(p, reg.SANCTIONS_CLEAR(), keccak256(abi.encode(p, "sanctions")));
    }

    function _lock(uint64 ttl) internal returns (bytes32 id) {
        vm.startPrank(dealer);
        bond.approve(address(htlc), 100_000);
        id = htlc.lock(address(bond), fund, 100_000, hashlock, uint64(block.timestamp) + ttl, SID, LEG);
        vm.stopPrank();
    }

    // ---- reason codes: same vocabulary as the conformance vectors ----

    function test_reasonCodes() public {
        assertEq(bond.otasCanTransfer(dealer, fund, 10), 0, "allowed");
        assertEq(bond.otasCanTransfer(dealer, stranger, 10), 11, "ineligible receiver");
        assertEq(bond.otasCanTransfer(stranger, fund, 0), 10, "ineligible sender");
        assertEq(bond.otasCanTransfer(dealer, fund, 2_000_000), 40, "insufficient units");
        reg.revokeClaim(fund, reg.SANCTIONS_CLEAR());
        assertEq(bond.otasCanTransfer(dealer, fund, 10), 23, "sanctions hit");
        reg.setFrozen(dealer, true);
        assertEq(bond.otasCanTransfer(dealer, fund, 10), 31, "frozen");
        reg.setPaused(true);
        assertEq(bond.otasCanTransfer(dealer, fund, 10), 30, "paused");
    }

    function test_transferDeniedCarriesReasonCode() public {
        vm.prank(dealer);
        vm.expectRevert(abi.encodeWithSelector(OTASDenied.selector, uint16(11)));
        bond.transfer(stranger, 1);
    }

    // ---- HTLC leg ----

    function test_lockClaim() public {
        bytes32 id = _lock(3600);
        assertEq(bond.balanceOf(address(htlc)), 100_000);
        htlc.claim(id, preimage); // anyone may submit; delivery is fixed to the receiver
        assertEq(bond.balanceOf(fund), 100_000);
        assertEq(bond.balanceOf(dealer), 900_000);
    }

    function test_lockDeniedWhenReceiverSanctioned() public {
        reg.revokeClaim(fund, reg.SANCTIONS_CLEAR());
        vm.startPrank(dealer);
        bond.approve(address(htlc), 100_000);
        vm.expectRevert(abi.encodeWithSelector(OTASDenied.selector, uint16(23)));
        htlc.lock(address(bond), fund, 100_000, hashlock, uint64(block.timestamp) + 3600, SID, LEG);
        vm.stopPrank();
    }

    function test_claimTimeRecheck() public {
        bytes32 id = _lock(3600);
        reg.revokeClaim(fund, reg.SANCTIONS_CLEAR()); // revoked between Committed and Settled
        vm.expectRevert(abi.encodeWithSelector(OTASDenied.selector, uint16(23)));
        htlc.claim(id, preimage);
        assertEq(bond.balanceOf(fund), 0);
    }

    function test_badPreimage() public {
        bytes32 id = _lock(3600);
        vm.expectRevert(OTASHTLC.BadPreimage.selector);
        htlc.claim(id, hex"00");
    }

    function test_refundAfterTimelock() public {
        bytes32 id = _lock(60);
        vm.expectRevert(OTASHTLC.NotExpired.selector);
        htlc.refund(id);
        vm.warp(block.timestamp + 61);
        vm.expectRevert(OTASHTLC.Expired.selector);
        htlc.claim(id, preimage);
        htlc.refund(id);
        assertEq(bond.balanceOf(dealer), 1_000_000);
    }

    function test_refundEvenIfSenderLaterSanctioned() public {
        bytes32 id = _lock(60);
        reg.revokeClaim(dealer, reg.SANCTIONS_CLEAR());
        vm.warp(block.timestamp + 61);
        htlc.refund(id);
        assertEq(bond.balanceOf(dealer), 1_000_000, "own units come back, not stranded");
    }

    function test_onlySystemAccountsReturnFromEscrow() public {
        vm.prank(dealer);
        vm.expectRevert(OTASBond.NotSystemAccount.selector);
        bond.returnFromEscrow(fund, 1);
    }

    function test_cannotReuseLockId() public {
        _lock(3600);
        vm.startPrank(dealer);
        bond.approve(address(htlc), 100_000);
        vm.expectRevert(OTASHTLC.LockExists.selector);
        htlc.lock(address(bond), fund, 100_000, hashlock, uint64(block.timestamp) + 3600, SID, LEG);
        vm.stopPrank();
    }
}
