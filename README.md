# 🔍 AI Fact Checker - Gonka Truth Engine

> Decentralized fact-checking engine using multi-model AI inference on the Gonka Network, with on-chain truth attestation on Arbitrum.

## 🌟 Project Overview

AI Fact Checker is a **decentralized "Truth Engine"** that uses multi-model AI (Pro Agent + Con Agent + Judge Agent) to verify the authenticity of news and social media claims in real-time.

### Key Features

- **Multi-Model Consensus**: Uses Gonka Router to call multiple AI models for cross-verification
- **Truth Score (0-100)**: Quantitative credibility score with detailed reasoning trace
- **On-Chain Attestation**: Stores verification results permanently on Arbitrum blockchain
- **Gonka Request ID Proof**: Every verification includes official Gonka Request IDs for transparency
- **Micro Bounty System**: Incentive mechanism for encouraging fact verification

## 🏗️ System Architecture

```
[Frontend] ── POST /api/verify ──> [FastAPI Backend]
                                           │
                                    [Gonka Router]
                                    /    |     \
                              Pro    Con   Judge  ← 3x Request IDs
                                           │
              <─── {truth_score, gonka_request_ids[]} ──┘
              │
         [Wallet] ── attestTruth() ──> [Arbitrum Blockchain]
                                        TruthRegistry.sol
```

## 👥 Team Members

| Role | Name |
|------|------|
| 队员 1 - AI Backend | PS |
| 队员 2 - Smart Contracts | PS二儿子 |
| 队员 3 - Frontend | PS大儿子 |
| 队员 4 - Pitch & Demo | TBD |

## 📁 Project Structure

```
aifactchecker/
├── 📄 README.md                 # This file
├── 📄 LICENSE                  # MIT License
├── 📁 docs/
│   ├── 📄 gonka-integration.md # Gonka Router integration guide
│   └── 📁 architecture.png     # System architecture diagram
├── 📁 backend/                 # 🚀 FastAPI + Gonka Router (队员 1)
│   ├── requirements.txt
│   ├── main.py
│   └── 📁 app/
│       ├── 📁 api/routes.py
│       ├── 📁 services/
│       │   ├── 📄 gonka_client.py      # 🌟 Gonka API wrapper
│       │   ├── 📄 consensus_agent.py   # Multi-model debate engine
│       │   └── 📄 search_engine.py     # Real-time web search
│       └── 📁 schemas/verify_schema.py  # Pydantic models
├── 📁 contracts/               # ⛓️ Smart Contracts (队员 2)
│   ├── foundry.toml
│   ├── .env.example
│   ├── 📁 src/
│   │   ├── 📄 TruthRegistry.sol  # 🌟 Core truth attestation
│   │   └── 📄 MicroBounty.sol    # 🪙 Bounty incentives
│   ├── 📁 script/Deploy.s.sol    # Deployment script
│   ├── 📁 test/TruthRegistry.t.sol  # Unit tests
│   └── 📁 abi/TruthRegistry.json # ABI for frontend
└── 📁 frontend/                 # 💻 Next.js + Wagmi (队员 3)
    ├── package.json
    └── 📁 src/
        ├── 📁 app/page.tsx           # Main UI
        ├── 📁 components/
        │   ├── 📄 RadarChart.tsx      # Score visualization
        │   ├── 📄 GonkaProofModal.tsx # Request ID display
        │   └── 📄 AttestButton.tsx    # On-chain attestation
        └── 📁 hooks/
            ├── 📄 useVerify.ts   # AI verification hook
            └── 📄 useAttest.ts   # Blockchain hook
```

## 🔗 Smart Contract Details (队员 2)

### TruthRegistry.sol

Core contract that permanently stores AI verification results on-chain.

**Key Data Structure - TruthRecord:**
```solidity
struct TruthRecord {
    bytes32  claimHash;          // keccak256 of the claim text
    uint8    truthScore;         // 0-100 score
    string   verdict;           // "TRUE" | "FALSE" | "DISPUTED"
    string[] gonkaRequestIds;    // 🌟 Array of Gonka Request IDs
    string   metadataURI;        // IPFS link to full debate log
    address  attester;           // Caller address
    uint256  timestamp;         // Immutable block timestamp
}
```

**Core Methods:**
- `attestTruth(...)` - Store verification result on-chain
- `getTruth(bytes32 claimHash)` - Read verification (free, public)
- `getGonkaRequestIds(bytes32 claimHash)` - Get Gonka Request IDs

### Deployment

| Network | Chain ID | Status |
|---------|----------|--------|
| Arbitrum Sepolia | 421614 | 🔄 Pending Deployment |
| Base Sepolia | 84532 | 🔄 Pending Deployment |

### Usage

```bash
# Install Foundry
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Navigate to contracts
cd contracts

# Install dependencies
forge install

# Run tests
forge test

# Deploy (requires .env with PRIVATE_KEY and RPC URL)
forge script script/Deploy.s.sol:DeployScript \
  --rpc-url arbitrum_sepolia \
  --broadcast \
  --private-key $PRIVATE_KEY
```

## 🎥 Demo & Video

- **Live Demo URL**: (队员 4 to add)
- **Pitch Video**: (队员 4 to add - 2 minute demo)
- **Deployed Contract**: (to be added after deployment)

## 📜 License

MIT License - See [LICENSE](./LICENSE)

## 🏆 Hackathon

This project was built for the **Gonka AI for Society Hackathon** - using decentralized AI for public truth verification.

---

**Built with ❤️ by Team AI Fact Checker**
