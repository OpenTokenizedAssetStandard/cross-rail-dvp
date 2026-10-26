// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// Numeric ids mirror schemas/reasons-v1.json. The same numbers are the Move abort
/// codes on the Sui leg, so a denial reads identically on both rails.
library OTASReasons {
    uint16 internal constant OTAS_OK = 0;
    uint16 internal constant INELIGIBLE_SENDER = 10;
    uint16 internal constant INELIGIBLE_RECEIVER = 11;
    uint16 internal constant SANCTIONS_HIT = 23;
    uint16 internal constant PAUSED = 30;
    uint16 internal constant FROZEN_ACCOUNT = 31;
    uint16 internal constant SUPPLY_RULE_VIOLATION = 40;
}

/// Raised by every OTAS contract on denial: the revert data carries the reason code.
error OTASDenied(uint16 reasonCode);
