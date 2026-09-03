// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {TruthRegistry} from "../src/TruthRegistry.sol";

/**
 * @title TruthRegistryTest
 * @notice Foundry unit tests for TruthRegistry.sol
 * @dev Run with: forge test
 *
 * Test Coverage:
 *  ✅ attestTruth() - basic truth attestation
 *  ✅ getTruth() - read verification
 *  ✅ isClaimAttested() - check attestation status
 *  ✅ getGonkaRequestIds() - retrieve request IDs
 *  ✅ hashClaim() - utility function
 *  ✅ Revert: duplicate attestation
 *  ✅ Revert: invalid verdict
 *  ✅ Revert: empty request IDs
 *  ✅ updateVerdict() - verdict update flow
 */
contract TruthRegistryTest is Test {
    TruthRegistry public truthRegistry;

    // Test data
    bytes32 public constant CLAIM_HASH = keccak256(abi.encodePacked("Trump announces free student loan relief"));
    uint8   public constant TRUTH_SCORE = 12;
    string  public constant VERDICT = "FALSE";
    string[] public GONKA_REQUEST_IDS = [
        "req_pro_agent_89f72b1",
        "req_con_agent_12a34c5",
        "req_judge_agent_99e81d0"
    ];
    string public constant METADATA_URI = "https://ipfs.io/ipfs/QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco";

    function setUp() public {
        truthRegistry = new TruthRegistry();
    }

    // ─────────────────────────────────────────────
    // Core Function Tests
    // ─────────────────────────────────────────────

    function test_attestTruth_success() public {
        bool result = truthRegistry.attestTruth(
            CLAIM_HASH,
            TRUTH_SCORE,
            VERDICT,
            GONKA_REQUEST_IDS,
            METADATA_URI
        );

        assertTrue(result, "attestTruth should return true");
    }

    function test_getTruth_returnsCorrectData() public {
        // Arrange
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);

        // Act 
        TruthRegistry.TruthRecord memory record = truthRegistry.getTruth(CLAIM_HASH);

        // Assert
        assertEq(record.claimHash, CLAIM_HASH, "claimHash mismatch");
        assertEq(record.truthScore, TRUTH_SCORE, "truthScore mismatch");
        assertEq(record.verdict, VERDICT, "verdict mismatch");
        assertEq(record.gonkaRequestIds.length, 3, "gonkaRequestIds length should be 3");
        assertEq(record.attester, address(this), "attester should be test contract");
        assertGt(record.timestamp, 0, "timestamp should be set");
    }

    function test_isClaimAttested_returnsTrue() public {
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);

        bool attested = truthRegistry.isClaimAttested(CLAIM_HASH);
        assertTrue(attested, "Claim should be attested");
    }

    function test_getGonkaRequestIds_returnsCorrectIds() public {
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);

        string[] memory ids = truthRegistry.getGonkaRequestIds(CLAIM_HASH);
        assertEq(ids.length, 3, "Should have 3 request IDs");
        assertEq(ids[0], "req_pro_agent_89f72b1");
        assertEq(ids[1], "req_con_agent_12a34c5");
        assertEq(ids[2], "req_judge_agent_99e81d0");
    }

    function test_hashClaim_generatesCorrectHash() public view{
        bytes32 hash = truthRegistry.hashClaim("Trump announces free student loan relief");
        assertEq(hash, CLAIM_HASH, "hashClaim should produce correct keccak256");
    }

    function test_totalAttestations_increments() public {
        assertEq(truthRegistry.totalAttestations(), 0, "Initial count should be 0");

        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);
        assertEq(truthRegistry.totalAttestations(), 1, "Count should be 1 after first attestation");

        bytes32 secondClaim = keccak256(abi.encodePacked("Second claim test"));
        truthRegistry.attestTruth(secondClaim, 85, "TRUE", GONKA_REQUEST_IDS, METADATA_URI);
        assertEq(truthRegistry.totalAttestations(), 2, "Count should be 2 after second attestation");
    }

    // ─────────────────────────────────────────────
    // Revert Tests
    // ─────────────────────────────────────────────

    function test_revert_duplicateAttestation() public {
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);

        vm.expectRevert("Claim already attested");
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);
    }

    function test_revert_invalidVerdict() public {
        vm.expectRevert("Invalid verdict");
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, "MAYBE", GONKA_REQUEST_IDS, METADATA_URI);
    }

    function test_revert_emptyRequestIds() public {
        string[] memory emptyIds = new string[](0);

        vm.expectRevert(TruthRegistry.EmptyRequestIds.selector);
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, emptyIds, METADATA_URI);
    }

    function test_revert_claimNotFound() public {
        bytes32 nonExistentHash = keccak256(abi.encodePacked("Non-existent claim"));

        vm.expectRevert("Claim not attested");
        truthRegistry.getTruth(nonExistentHash);
    }

    // ─────────────────────────────────────────────
    // Verdict Update Tests
    // ─────────────────────────────────────────────

    function test_updateVerdict_success() public {
        // Attest first
        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);

        // Update to DISPUTED
        truthRegistry.updateVerdict(CLAIM_HASH, "DISPUTED");

        TruthRegistry.TruthRecord memory record = truthRegistry.getTruth(CLAIM_HASH);
        assertEq(record.verdict, "DISPUTED", "Verdict should be updated to DISPUTED");
    }

    // ─────────────────────────────────────────────
    // Event Tests
    // ─────────────────────────────────────────────

    function test_event_TruthAttested_emitted() public {
        vm.expectEmit(true, true, true, true);
        emit TruthRegistry.TruthAttested(
            CLAIM_HASH,
            TRUTH_SCORE,
            VERDICT,
            GONKA_REQUEST_IDS,
            address(this),
            block.timestamp
        );

        truthRegistry.attestTruth(CLAIM_HASH, TRUTH_SCORE, VERDICT, GONKA_REQUEST_IDS, METADATA_URI);
    }
}