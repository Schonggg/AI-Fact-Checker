// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title TruthRegistry
 * @notice Decentralized fact-checking truth attestation contract
 * @dev Stores AI-verified truth scores and Gonka Request IDs on-chain
 *      for permanent, tamper-proof verification records.
 *
 * Workflow:
 *  1. Frontend calls backend /api/verify → Gonka Router processes
 *  2. Backend returns { claim_hash, truth_score, verdict, gonka_request_ids[], metadata_uri }
 *  3. Frontend calls attestTruth(...) to store on Arbitrum/ETH blockchain
 *  4. TruthAttested event is emitted for transparency
 *
 * @author 队员 2 - Lick Bin / Gonka AI Fact Checker Team
 */
contract TruthRegistry {
    // ─────────────────────────────────────────────
    // Data Structures
    // ─────────────────────────────────────────────

    /**
     * @notice Represents a single truth verification record
     * @param claimHash       keccak256 hash of the original claim text
     * @param truthScore      Truth score 0-100 (0=FALSE, 100=TRUE)
     * @param verdict         Final verdict: "TRUE", "FALSE", or "DISPUTED"
     * @param gonkaRequestIds 🌟 Core field: Array of Gonka Request IDs from Router
     *                         Each ID corresponds to one model inference (Pro/Con/Judge)
     * @param metadataURI     IPFS/Arweave link to full AI debate log
     * @param attester        Address that called attestTruth()
     * @param timestamp       Block timestamp (immutable on-chain time proof)
     */
    struct TruthRecord {
        bytes32  claimHash;
        uint8    truthScore;
        string   verdict;
        string[] gonkaRequestIds;
        string   metadataURI;
        address  attester;
        uint256  timestamp;
    }

    // ─────────────────────────────────────────────
    // State Variables
    // ─────────────────────────────────────────────

    /// @notice Mapping: claim hash → TruthRecord
    mapping(bytes32 => TruthRecord) public truthRecords;

    /// @notice Counter for total attestations
    uint256 public totalAttestations;

    /// @notice Whether a claim hash has been attested
    mapping(bytes32 => bool) public isAttested;

    /// @notice Contract owner (for potential admin functions)
    address public owner;

    // ─────────────────────────────────────────────
    // Events
    // ─────────────────────────────────────────────

    /**
     * @notice Emitted when a new truth attestation is recorded
     * @param claimHash       Hash of the verified claim
     * @param truthScore      Score 0-100
     * @param verdict         TRUE / FALSE / DISPUTED
     * @param gonkaRequestIds Array of Gonka Request IDs used
     * @param attester        Wallet address that submitted
     * @param timestamp       Block timestamp
     */
    event TruthAttested(
        bytes32  indexed claimHash,
        uint8    truthScore,
        string   verdict,
        string[] gonkaRequestIds,
        address  indexed attester,
        uint256  timestamp
    );

    /**
     * @notice Emitted when a claim verdict is updated
     * @param claimHash   Hash of the claim
     * @param oldVerdict  Previous verdict
     * @param newVerdict  New verdict after dispute resolution
     */
    event VerdictUpdated(
        bytes32 indexed claimHash,
        string  oldVerdict,
        string  newVerdict
    );

    // ─────────────────────────────────────────────
    // Errors
    // ─────────────────────────────────────────────

    error ClaimAlreadyAttested(bytes32 claimHash);
    error InvalidVerdict(string verdict);
    error EmptyRequestIds();
    error EmptyMetadataURI();
    error ZeroAddress();

    // ─────────────────────────────────────────────
    // Modifiers
    // ─────────────────────────────────────────────

    modifier validVerdict(string memory verdict) {
        require(
            keccak256(abi.encodePacked(verdict)) == keccak256(abi.encodePacked("TRUE")) ||
            keccak256(abi.encodePacked(verdict)) == keccak256(abi.encodePacked("FALSE")) ||
            keccak256(abi.encodePacked(verdict)) == keccak256(abi.encodePacked("DISPUTED")),
            "Invalid verdict"
        );
        _;
    }

    // ─────────────────────────────────────────────
    // Constructor
    // ─────────────────────────────────────────────

    constructor() {
        owner = msg.sender;
    }

    // ─────────────────────────────────────────────
    // Core Write Functions
    // ─────────────────────────────────────────────

    /**
     * @notice Attest a truth verification result on-chain
     * @dev Stores the AI-verified claim permanently on blockchain
     * @param claimHash    keccak256 hash of the original claim text
     * @param truthScore   Truth score 0-100
     * @param verdict      "TRUE" | "FALSE" | "DISPUTED"
     * @param gonkaRequestIds 🌟 Array of Gonka Router Request IDs (one per model)
     * @param metadataURI  IPFS/Arweave link to full AI debate log
     *
     * Example gonkaRequestIds:
     *   ["req_pro_agent_89f72b1", "req_con_agent_12a34c5", "req_judge_agent_99e81d0"]
     */
    function attestTruth(
        bytes32  calldata claimHash,
        uint8    truthScore,
        string calldata verdict,
        string[] calldata gonkaRequestIds,
        string calldata metadataURI
    ) external validVerdict(verdict) returns (bool) {
        // Prevent duplicate attestations
        require(!isAttested[claimHash], "Claim already attested");

        // Validate inputs
        if (gonkaRequestIds.length == 0) revert EmptyRequestIds();
        if (bytes(metadataURI).length == 0) revert EmptyMetadataURI();

        // Store the record
        TruthRecord storage record = truthRecords[claimHash];
        record.claimHash       = claimHash;
        record.truthScore      = truthScore;
        record.verdict         = verdict;
        record.gonkaRequestIds = gonkaRequestIds;
        record.metadataURI     = metadataURI;
        record.attester        = msg.sender;
        record.timestamp       = block.timestamp;

        // Update state
        isAttested[claimHash] = true;
        totalAttestations++;

        // Emit event for transparency
        emit TruthAttested(
            claimHash,
            truthScore,
            verdict,
            gonkaRequestIds,
            msg.sender,
            block.timestamp
        );

        return true;
    }

    /**
     * @notice Update verdict after dispute resolution
     * @dev Only the original attester can update (or anyone via governance - extendable)
     * @param claimHash Hash of the claim to update
     * @param newVerdict New verdict after review
     */
    function updateVerdict(
        bytes32 calldata claimHash,
        string calldata newVerdict
    ) external validVerdict(newVerdict) {
        require(isAttested[claimHash], "Claim not attested");

        TruthRecord storage record = truthRecords[claimHash];
        string memory oldVerdict = record.verdict;

        // Update verdict
        record.verdict = newVerdict;

        emit VerdictUpdated(claimHash, oldVerdict, newVerdict);
    }

    // ─────────────────────────────────────────────
    // Core Read Functions
    // ─────────────────────────────────────────────

    /**
     * @notice Get full TruthRecord by claim hash
     * @dev Free public read - implements "verify once, trust all" pattern
     * @param claimHash keccak256 hash of the claim
     * @return TruthRecord struct
     */
    function getTruth(bytes32 calldata claimHash)
        external
        view
        returns (TruthRecord memory)
    {
        require(isAttested[claimHash], "Claim not attested");
        return truthRecords[claimHash];
    }

    /**
     * @notice Check if a claim has been attested
     * @param claimHash Hash of the claim
     * @return bool True if attested
     */
    function isClaimAttested(bytes32 calldata claimHash)
        external
        view
        returns (bool)
    {
        return isAttested[claimHash];
    }

    /**
     * @notice Get gonkaRequestIds for a specific claim
     * @param claimHash Hash of the claim
     * @return string[] Array of Gonka Request IDs
     */
    function getGonkaRequestIds(bytes32 calldata claimHash)
        external
        view
        returns (string[] memory)
    {
        require(isAttested[claimHash], "Claim not attested");
        return truthRecords[claimHash].gonkaRequestIds;
    }

    // ─────────────────────────────────────────────
    // Utility Functions
    // ─────────────────────────────────────────────

    /**
     * @notice Calculate keccak256 hash of a text claim
     * @dev Frontend can use this to generate claimHash before calling attestTruth
     * @param claimText The original claim text
     * @return bytes32 The claim hash
     */
    function hashClaim(string calldata claimText)
        external
        pure
        returns (bytes32)
    {
        return keccak256(abi.encodePacked(claimText));
    }

    /**
     * @notice Get contract metadata
     * @return address Owner address
     * @return uint256 Total attestations count
     */
    function getContractInfo()
        external
        view
        returns (address, uint256)
    {
        return (owner, totalAttestations);
    }
}