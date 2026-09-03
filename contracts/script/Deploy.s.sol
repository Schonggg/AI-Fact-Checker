// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {TruthRegistry} from "../src/TruthRegistry.sol";
import {MicroBounty} from "../src/MicroBounty.sol";

/**
 * @title DeployScript
 * @notice Foundry deployment script for TruthRegistry & MicroBounty on Arbitrum Sepolia
 * @dev Usage:
 *       forge script script/Deploy.s..sol:DeployScript \
 *         --rpc-url arbitrum_sepolia \
 *         --broadcast \
 *         --private-key $PRIVATE_KEY \
 *         --verify
 *
 * Environment Variables Required:
 *       ARB_SEPOIIA_RPC_URL - Arbitrum Sepolia RPC (e.g. https://arb-sepolia.g.alchemy.com/v2/...)
 *       PRIVATE_KEY         - Deployer wallet private key
 *       ARBISCAN_API_KEY    - Arbiscan API key for verification
 */
contract DeployScript is Script {
    // ─────────────────────────────────────────────
    // Chain Configuration
    // ─────────────────────────────────────────────

    uint256 constant ARBITRUM_SEPOLIA_CHAIN_ID = 421614;

    // ─────────────────────────────────────────────
    // Deployment
    // ─────────────────────────────────────────────

    function run() external {
        // 1. Load environment variables
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        string memory rpcUrl = vm.envString("ARB_SEPOLIA_RPC_URL");

        console.log("Deploying to Arbitrum Sepolia...");
        console.log("Chain ID:", ARBITRUM_SEPOLIA_CHAIN_ID);
        console.log("Deployer:", vm.addr(deployerPrivateKey));

        // 2. Set RPC
        vm.createSelectFork(rpcUrl);

        // 3. Start broadcast
        vm.startBroadcast(deployerPrivateKey);

        // 4. Deploy TruthRegistry first (no constructor args)
        TruthRegistry truthRegistry = new TruthRegistry();
        console.log("TruthRegistry deployed at:", address(truthRegistry));

        // 5. Deploy MicroBounty (needs TruthRegistry address)
        MicroBounty microBounty = new MicroBounty(address(truthRegistry));
        console.log("MicroBounty deployed at:", address(microBounty));

        // 6. Stop broadcast
        vm.stopBroadcast();

        // 7. Log deployment addresses
        console.log("");
        console.log("=== Deployment Summary ===");
        console.log("TruthRegistry:", address(truthRegistry));
        console.log("MicroBounty:", address(microBounty));
        console.log("");
        console.log("Add these to your .env and frontend contracts/addresses.ts:");
        console.log("TRUTH_REGISTRY_ADDRESS=", address(truthRegistry));
        console.log("MICRO_BOUNTY_ADDRESS=", address(microBounty));
        console.log("CHAIN_ID=", ARBITRUM_SEPOLIA_CHAIN_ID);

        // 8. Verify on Arbiscan
        verifyContract(address(truthRegistry), "TruthRegistry");
        verifyContract(address(microBounty), "MicroBounty");
    }

    function verifyContract(address deployedAddress, string memory contractName) internal {
        try vm.envString("ARBISCAN_API_KEY") returns (string memory apiKey) {
            if (bytes(apiKey).length > 0) {
                console.log("Verifying", contractName, "on Arbiscan...");
                // Note: actual verification requires forge-verify or hardhat-verify
                // Run separately: forge verify-contract <address> --constructor-args ...
            }
        } catch {
            console.log("Skipping verification (no ARBISCAN_API_KEY)"); 
        }
    }
}