// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title MicroBounty
 * @notice Decentralized micro-bounty system for fact verification incentives
 * @dev Allows users to fund verification requests and rewards verifiers
 *
 * Flow:
 *  1. User calls fundVerification(claimHash) with ETH
 *  2. Attester calls claimBounty() after successful attestation
 *  3. Bounty is transferred to the attester
 *
 * @author 队员 2 - Lick Bin / Gonka AI Fact Checker Team
 */
contract MicroBounty {
    // ─────────────────────────────────────────────
    // Data Structures
    // ─────────────────────────────────────────────

    struct Bounty {
        uint256 amount;      // ETH amount funded
        address funder;      // Who funded it
        bool    claimed;     // Whether bounty has been paid out
        uint256 timestamp;   // When it was funded
    }

    // ─────────────────────────────────────────────
    // State Variables
    // ─────────────────────────────────────────────

    /// @notice Mapping: claim hash → Bounty info
    mapping(bytes32 => Bounty) public bounties;

    /// @notice Minimum bounty amount (e.g., 0.001 ETH)
    uint256 public constant MIN_BOUNTY = 0.001 ether;

    /// @notice Treasury address for unclaimed bounties
    address public treasury;

    /// @notice TruthRegistry contract reference (to verify attestations)
    address public truthRegistry;

    // ─────────────────────────────────────────────
    // Events
    // ─────────────────────────────────────────────

    event BountyFunded(
        bytes32 indexed claimHash,
        address indexed funder,
        uint256 amount
    );

    event BountyClaimed(
        bytes32 indexed claimHash,
        address indexed recipient,
        uint256 amount
    );

    // ─────────────────────────────────────────────
    // Errors
    // ─────────────────────────────────────────────

    error InsufficientBounty();
    error BountyAlreadyClaimed(bytes32 claimHash);
    error BountyNotFound(bytes32 claimHash);
    error ClaimNotAttested(bytes32 claimHash);
    error TransferFailed();

    // ─────────────────────────────────────────────
    // Constructor
    // ─────────────────────────────────────────────

    constructor(address _truthRegistry) {
        treasury = msg.sender;
        truthRegistry = _truthRegistry;
    }

    // ─────────────────────────────────────────────
    // Write Functions
    // ─────────────────────────────────────────────

    /**
     * @notice Fund a verification bounty for a claim
     * @dev Anyone can fund, amount must be >= MIN_BOUNTY
     * @param claimHash Hash of the claim to be verified
     */
    function fundVerification(bytes32 claimHash) external payable {
        if (msg.value < MIN_BOUNTY) revert InsufficientBounty();

        Bounty storage bounty = bounties[claimHash];
        bounty.amount    += msg.value;
        bounty.funder    = msg.sender;
        bounty.timestamp = block.timestamp;

        emit BountyFunded(claimHash, msg.sender, msg.value);
    }

    /**
     * @notice Claim bounty after successful attestation
     * @dev Must be called after TruthRegistry.attestTruth() for the same claimHash
     * @param claimHash Hash of the attested claim
     */
    function claimBounty(bytes32 claimHash) external {
        Bounty storage bounty = bounties[claimHash];

        if (bounty.amount == 0) revert BountyNotFound(claimHash);
        if (bounty.claimed) revert BountyAlreadyClaimed(claimHash);

        // Verify the claim is attested on TruthRegistry
        bool attested = ITruthRegistry(truthRegistry).isClaimAttested(claimHash);
        if (!attested) revert ClaimNotAttested(claimHash);

        bounty.claimed = true;
        uint256 payout = bounty.amount;

        // Transfer ETH to msg.sender
        (bool success, ) = msg.sender.call{value: payout}("");
        if (!success) revert TransferFailed();

        emit BountyClaimed(claimHash, msg.sender, payout);
    }

    /**
     * @notice Update treasury address
     * @param newTreasury New treasury address
     */
    function updateTreasury(address newTreasury) external {
        require(msg.sender == treasury, "Only treasury");
        treasury = newTreasury;
    }

    // ─────────────────────────────────────────────
    // Read Functions
    // ─────────────────────────────────────────────

    /**
     * @notice Get bounty info for a claim
     * @param claimHash Hash of the claim
     * @return amount    ETH amount
     * @return funder    Funder address
     * @return claimed   Whether claimed
     * @return timestamp When funded
     */
    function getBounty(bytes32 claimHash)
        external
        view
        returns (uint256 amount, address funder, bool claimed, uint256 timestamp)
    {
        Bounty memory b = bounties[claimHash];
        return (b.amount, b.funder, b.claimed, b.timestamp);
    }
} // （microbounty contracts endin

/**
 * @notice Minimal interface for TruthRegistry read operations
 * @dev Only what MicroBounty needs to verify attestations
 */
interface ITruthRegistry {
    function isClaimAttested(bytes32 claimHash) external view returns (bool);
    
    function getTruth(bytes32 claimHash)
        external
        view
        returns (
            bytes32  claimHash_,
            uint8    truthScore,
            string memory verdict,
            string[] memory gonkaRequestIds,
            string memory metadataURI,
            address attester,
            uint256 timestamp
        );
}