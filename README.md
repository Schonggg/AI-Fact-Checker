# GONKA AI Fact Checker

GONKA AI Fact Checker is a decentralized fact-checking web application that verifies claims through a three-agent AI debate flow, prepares evidence for IPFS storage, and enables verified results to be attested on-chain through a TruthRegistry smart contract on Arbitrum Sepolia.

Users can submit either a text claim or a public HTTPS article URL. The backend gathers available evidence, routes the claim through Gonka Router models, aggregates the Pro / Con / Judge outputs into a final verdict, and returns a structured result that the frontend can display and, when eligible, mint as an on-chain truth attestation.

## Contents

- [Core Functionality](#core-functionality)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [API Reference](#api-reference)
- [On-Chain Attestation Flow](#on-chain-attestation-flow)
- [Smart Contracts](#smart-contracts)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [License](#license)

## Core Functionality

- **Three-agent adversarial verification**: Kimi acts as the Pro agent, DeepSeek acts as the Con agent, and MiniMax acts as the Judge.
- **Gonka Router integration**: all model calls are sent through the OpenAI-compatible Gonka Router API, and successful model calls return Gonka request IDs as proof of inference.
- **Claim and URL support**: users can submit plain text claims or public HTTPS article links.
- **Article extraction**: public article pages are fetched server-side and converted into readable evidence text.
- **Optional web search**: Tavily can be used to retrieve real-time background sources for text-only claims.
- **Consensus verdict**: the backend aggregates model outputs into `true`, `false`, `misleading`, or `unverified`.
- **Truth score and metrics**: each verification returns a 0-100 truth score, confidence score, model summaries, references, risk flags, and radar-chart metrics.
- **Keccak claim hash**: claims are normalized and hashed with Keccak-256 to match the Solidity contract format.
- **IPFS evidence bundle**: when `PINATA_JWT` is configured, the backend pins the complete verification result to IPFS through Pinata.
- **Wallet-based attestation**: the frontend can connect an injected EVM wallet, switch to Arbitrum Sepolia, and call `TruthRegistry.attestTruth(...)` for eligible results.
- **Live on-chain dashboard**: the frontend reads recent `TruthAttested` events from the deployed TruthRegistry contract.

## System Architecture

```text
Browser / Static Frontend
        |
        | submit claim or HTTPS article URL
        v
POST /api/verify
        |
        |-- validate input and settings
        |-- fetch article text when URL is supplied
        |-- optionally discover/search sources with Tavily
        |-- check available Gonka Router models
        |
        |-- Pro agent:   Kimi (Fallback to MiniMax)
        |-- Con agent:   DeepSeek
        |-- Judge agent: MiniMax, using Pro/Con debate context
        |
        |-- aggregate verdict, score, metrics, references, and risks
        |-- generate Keccak claim hash and evidence hash
        |-- optionally pin full result to IPFS through Pinata
        v
Verification JSON response
        |
        | frontend displays analysis and attestation certificate
        v
Connected wallet calls TruthRegistry.attestTruth(...)
        |
        v
Arbitrum Sepolia TruthRegistry event log
```

A result can only be attested when it is not `unverified`, contains at least three Gonka request IDs, and has a valid `metadataURI` from IPFS pinning.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Static HTML, React 18 UMD, Tailwind CDN, ethers.js |
| Active backend | Python serverless handler in `api/verify.py` |
| Local server | `server.py`, serving `public/` and forwarding `/api/verify` |
| AI routing | Gonka Router OpenAI-compatible API |
| Search | Tavily Search API, optional |
| IPFS pinning | Pinata API, optional but required for on-chain-ready attestations |
| Claim hashing | Keccak-256 via `pycryptodome` |
| Blockchain | Arbitrum Sepolia |
| Smart contracts | Solidity `^0.8.24`, Foundry |
| Deployment | Vercel static hosting plus Python serverless functions |

## Repository Structure

```text
.
├── api/
│   ├── health.py                 # Serverless health check
│   └── verify.py                 # Main verification API and Vercel handler
├── public/
│   └── index.html                # Static React frontend, wallet flow, dashboard
├── backend/
│   └── app/
│       ├── core/web3_config.py   # Shared Arbitrum/TruthRegistry constants
│       └── services/claim_parser.py
│                                  # Claim normalization, Keccak hash, verdict mapping
├── contracts/
│   ├── src/
│   │   ├── TruthRegistry.sol     # On-chain truth attestation registry
│   │   └── MicroBounty.sol       # Optional bounty incentive contract
│   ├── script/Deploy.s.sol       # Foundry deployment script
│   ├── test/TruthRegistry.t.sol  # Contract unit tests
│   ├── abi/TruthRegistry.json    # ABI artifact for frontend/reference use
│   └── foundry.toml              # Foundry configuration
├── Muba Blockchain Hackathon (Gonka Router)/
│                                  # Archived/copy variant of the same app
├── .env.example                  # Root environment template
├── requirements.txt              # Python dependency list for root API
├── server.py                     # Local development server
├── vercel.json                   # Vercel config
├── LICENSE
└── README.md
```

The active final app is the root-level `api/`, `public/`, `server.py`, and `contracts/` setup. The `backend/` directory is not the primary FastAPI runtime in this final version, but the root API does import shared helper modules from it.

## Environment Variables

Create `.env.local` in the project root for local development:

```bash
cp .env.example .env.local
```

### Required

| Variable | Description |
| --- | --- |
| `GONKA_API_KEY` | Gonka Router API key. Required for `POST /api/verify`. Without it, the API returns `503`. |

### Recommended

| Variable | Description | Default |
| --- | --- | --- |
| `TAVILY_API_KEY` | Enables real-time source retrieval for text claims. Without it, verification still runs using model/source discovery only. | Empty |
| `TAVILY_MAX_RESULTS` | Maximum number of search results included as evidence. | `5` |
| `PINATA_JWT` | Pinata JWT used to pin the verification result to IPFS. Required if you want the frontend attestation button to become eligible. | Empty |
| `PINATA_TIMEOUT` | Pinata request timeout in seconds. | `8` |

### Optional Gonka Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `GONKA_BASE_URL` | Gonka Router base URL. Must be an absolute HTTPS URL ending at the `/v1` broker base. | `https://api.gonkarouter.io/v1` |
| `GONKA_DEEPSEEK_MODEL` | DeepSeek model used as the Con agent. | `deepseek-ai/DeepSeek-V4-Flash-0731` |
| `GONKA_KIMI_MODEL` | Kimi model used as the Pro agent. | `moonshotai/Kimi-K2.6` |
| `GONKA_MINIMAX_MODEL` | MiniMax model used as the Judge agent. | `MiniMaxAI/MiniMax-M2.7` |
| `GONKA_FALLBACK_MODEL` | Fallback model used when Kimi fails or times out. | `MiniMaxAI/MiniMax-M2.7` |
| `GONKA_MODEL_TIMEOUT` | General model request timeout in seconds. | `45` |
| `GONKA_KIMI_MODEL_TIMEOUT` | Kimi-specific timeout in seconds. | `30` |
| `GONKA_ARTICLE_TIMEOUT` | Article fetch timeout in seconds. | `15` |
| `GONKA_TOTAL_BUDGET_SECONDS` | Overall request budget. Keep below Vercel's function limit. | `56` |
| `GONKA_ANALYSIS_STAGE_BUDGET_SECONDS` | Maximum time reserved for the parallel Pro/Con analysis stage. | `15` |
| `GONKA_JUDGE_STAGE_RESERVE_SECONDS` | Time reserved for the final Judge stage. | `40` |
| `GONKA_ALLOWED_ORIGIN` | CORS allow-origin value. Use a specific domain in production if needed. | `*` |
| `LOG_LEVEL` | Backend log level. | `INFO` |

### Contract Addresses

The current frontend and environment template point to Arbitrum Sepolia:

| Variable | Description | Current value |
| --- | --- | --- |
| `TRUTH_REGISTRY_ADDRESS` | Deployed TruthRegistry contract address. | `0xb0DeedAe473dc32DD2B69bFdEc554e3b34119c58` |
| `MICRO_BOUNTY_ADDRESS` | Deployed MicroBounty contract address. | `0xb391DB173D6211e246b174F91E790662C5Bb9a24` |
| `CHAIN_ID` | Arbitrum Sepolia chain ID. | `421614` |

## Local Development

### 1. Install Python dependencies

The final root API requires `pycryptodome` for Keccak-256 hashing:

```bash
python -m pip install -r requirements.txt
```

### 2. Configure local environment

```bash
cp .env.example .env.local
```

At minimum, set:

```env
GONKA_API_KEY=your_gonka_router_api_key
```

For the complete final flow, also set:

```env
TAVILY_API_KEY=your_tavily_api_key
PINATA_JWT=your_pinata_jwt
```

### 3. Start the local app

```bash
python server.py
```

Default local URLs:

- Frontend: `http://127.0.0.1:3000/`
- API status: `http://127.0.0.1:3000/api/verify`
- Verification endpoint: `POST http://127.0.0.1:3000/api/verify`

Optional host/port override:

```bash
HOST=127.0.0.1 PORT=3000 python server.py
```

### 4. Use the app

1. Open `http://127.0.0.1:3000/`.
2. Enter a claim or paste a public HTTPS article URL.
3. Run verification.
4. Review the final verdict, truth score, model debate, source list, raw JSON, and attestation certificate.
5. Connect an EVM wallet if you want to submit an eligible result to Arbitrum Sepolia.

The frontend automatically uses `http://127.0.0.1:3000/api/verify` in local mode and same-origin `/api/verify` in production. You can override the API host with:

```text
?api=https://your-api-host.example
```

## API Reference

### `GET /api/health`

Simple deployment health check.

Example response:

```json
{
  "status": "ok",
  "service": "ai-fact-checker"
}
```

### `GET /api/verify`

Returns API configuration status, configured model IDs, available Gonka models when the key is valid, and the expected request format.

Important status values:

- `ok`
- `missing_api_key`
- `configuration_error`

### `POST /api/verify`

Runs the full verification workflow.

Request body:

```json
{
  "claim": "The Eiffel Tower is located in Paris.",
  "settings": {
    "language": "en",
    "webSearch": true,
    "agents": {
      "kimi": true,
      "deepseek": true,
      "minimax": true
    }
  }
}
```

Notes:

- `claim` accepts plain text or a public HTTPS article URL.
- All three agents must be enabled in the final Pro / Con / Judge flow.
- Inputs longer than 12,000 characters are rejected.
- Article extraction is limited to 28,000 readable characters.

Main response fields:

| Field | Description |
| --- | --- |
| `id` | Generated verification ID. |
| `status` | `ok`, `partial`, or `error`. |
| `claim` | Original submitted claim or URL. |
| `inputType` | `text` or `url`. |
| `article` | Extracted article metadata and text when a URL is used. |
| `verdict` | `true`, `false`, `misleading`, or `unverified`. |
| `truthScore` | Weighted 0-100 truth score. |
| `confidence` | Aggregated confidence score. |
| `consensus` | Model agreement summary. |
| `summary` | Final human-readable conclusion. |
| `metrics` | Factual accuracy, source quality, logical consistency, bias neutrality, temporal consistency, and consensus. |
| `models` | Per-model result objects, including provider, model, role, score, confidence, request ID, fallback state, and summary. |
| `references` | Article, Tavily, or model-supplied references. |
| `riskFlags` | Warnings such as missing search, failed article extraction, or Pinata issues. |
| `attestation` | Claim hash, evidence hash, schema, network, protocol, Gonka request IDs, IPFS metadata URI, contract verdict, and minting status. |
| `search` | Search query and source summary when web search is used. |
| `timings` | Total latency, model latency, and Pinata configuration status. |

Example:

```bash
curl -X POST http://127.0.0.1:3000/api/verify \
  -H "Content-Type: application/json" \
  -d '{"claim":"The Eiffel Tower is located in Paris.","settings":{"language":"en","webSearch":true,"agents":{"kimi":true,"deepseek":true,"minimax":true}}}'
```

Common errors:

| HTTP Status | Meaning |
| --- | --- |
| `400` | Missing claim, invalid JSON, or not all three agents are enabled. |
| `413` | Input exceeds the maximum supported length. |
| `502` | Gonka Router connection, model availability, or configuration problem. |
| `503` | `GONKA_API_KEY` is missing. |

## On-Chain Attestation Flow

The frontend can submit a result to `TruthRegistry` only when all of the following are true:

1. A wallet is connected through an injected EVM provider such as MetaMask.
2. The wallet is on Arbitrum Sepolia, or the app can request a network switch.
3. The verification verdict is not `unverified`.
4. The backend returned at least three Gonka request IDs.
5. Pinata successfully pinned the verification JSON and returned `metadataURI`.
6. The backend mapped the verdict to the contract format:
   - `true` -> `TRUE`
   - `false` -> `FALSE`
   - `misleading` -> `DISPUTED`

When the user confirms the wallet transaction, the frontend calls:

```solidity
attestTruth(bytes32 claimHash, uint8 truthScore, string verdict, string[] gonkaRequestIds, string metadataURI)
```

After confirmation, the app verifies that the transaction emitted a matching `TruthAttested` event.

## Smart Contracts

The `contracts/` folder contains a Foundry project.

### `TruthRegistry.sol`

Stores one immutable-style truth record per claim hash. Each `TruthRecord` contains:

- `claimHash`
- `truthScore`
- `verdict`
- `gonkaRequestIds`
- `metadataURI`
- `attester`
- `timestamp`

Key functions:

| Function | Purpose |
| --- | --- |
| `attestTruth(...)` | Writes a new fact-checking result on-chain. |
| `getTruth(bytes32)` | Reads the stored record for a claim hash. |
| `isClaimAttested(bytes32)` | Checks whether a claim hash already has an attestation. |
| `getGonkaRequestIds(bytes32)` | Reads the Gonka request IDs associated with a claim. |
| `hashClaim(string)` | Computes the contract-side Keccak-256 hash. |
| `updateVerdict(bytes32,string)` | Updates a recorded verdict after review or dispute handling. |

Accepted contract verdicts are `TRUE`, `FALSE`, and `DISPUTED`.

### `MicroBounty.sol`

Provides an optional incentive layer:

- anyone can fund a verification bounty for a claim hash,
- the bounty must be at least `0.001 ether`,
- a verifier can claim the bounty after the claim is attested in `TruthRegistry`.

### Contract Development

From the `contracts/` directory:

```bash
forge test
```

To deploy to Arbitrum Sepolia:

```bash
cp .env.example .env
forge script script/Deploy.s.sol:DeployScript \
  --rpc-url arbitrum_sepolia \
  --broadcast \
  --private-key $PRIVATE_KEY
```

Never commit real private keys. Use a testnet burner wallet.

## Deployment

### Vercel

This repository is structured for Vercel deployment:

- `public/index.html` is served as the static frontend.
- `api/verify.py` and `api/health.py` are Python serverless functions.
- `requirements.txt` installs `pycryptodome`, required by the Keccak hash helper.

Deployment steps:

1. Import the repository into Vercel.
2. Add the root environment variables in Project Settings.
3. Set `GONKA_API_KEY`.
4. Set `PINATA_JWT` if the deployed app should support on-chain-ready IPFS metadata.
5. Optionally set `TAVILY_API_KEY` for live source search.
6. Deploy.
7. Test `GET /api/verify`, then run a claim verification from the frontend.

### Frontend API override

If the frontend is hosted separately from the API, provide an API base through the URL:

```text
https://your-frontend.example/?api=https://your-api.example
```

The frontend also supports a global `window.GONKA_API_BASE` override if you choose to define it before the app runs.

## Troubleshooting

| Problem | Likely Cause | Fix |
| --- | --- | --- |
| `Server is missing GONKA_API_KEY` | Gonka key is not configured. | Add `GONKA_API_KEY` to `.env.local` or Vercel environment variables. |
| `Configured model IDs are not available` | The configured model names do not exist in the broker `/models` response. | Open `GET /api/verify`, inspect available models, and update `GONKA_*_MODEL`. |
| Attestation button is disabled | Result is unverified, wallet is disconnected, fewer than three request IDs were returned, or Pinata did not return `metadataURI`. | Connect wallet, verify a supported claim, and configure `PINATA_JWT`. |
| Wallet cannot switch networks | Wallet rejected or does not support Arbitrum Sepolia. | Add Arbitrum Sepolia manually and retry. |
| Article URL fails | URL is not public HTTPS, redirects to a private address, blocks server-side access, or exposes too little readable text. | Use a public HTTPS article or submit the claim as text. |
| `/api/verify` returns 404 or 405 locally | The frontend is being served by a static-only server. | Run `python server.py` from the repository root. |
| Verification times out | Gonka model or broker request is slow. | Increase timeout variables or retry later. |
| Search references are missing | Tavily is not configured or the search request failed. | Add `TAVILY_API_KEY`; verification can still run without it. |
| IPFS metadata is missing | Pinata is not configured or upload failed. | Add `PINATA_JWT` and check Pinata account/API permissions. |

## Security Notes

- Do not commit `.env`, `.env.local`, private keys, Pinata JWTs, or API keys.
- Use a burner wallet for testnet contract deployment and demo transactions.
- The backend rejects non-public and non-HTTPS article URLs to reduce SSRF risk.
- AI verification should be treated as evidence-assisted analysis, not an absolute legal or journalistic determination.
- Restrict `GONKA_ALLOWED_ORIGIN` to the production frontend origin when deploying publicly.
- The frontend contract address is hardcoded in `public/index.html`; update it if you redeploy `TruthRegistry`.

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.
