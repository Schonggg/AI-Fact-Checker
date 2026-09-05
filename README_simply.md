# GONKA AI Fact Checker

### Verify claims. See the evidence. Prove the result.

GONKA AI Fact Checker is a decentralized AI-powered fact-checking application.
It helps you verify whether a claim or article is **true, false, misleading, or unverified**.
Instead of relying on a single AI model, the system uses three different AI agents to debate the claim.

## 🔍 How It Works

### 1. Submit a Claim

Enter either:

* A text claim
* A public HTTPS article URL

If you submit an article, the system extracts the readable article content automatically.

### 2. Gather Evidence

The system analyzes the claim and can search for additional real-time sources.

Article content, search results, and model-provided references are collected as supporting evidence.

### 3. AI Debate

Three AI agents independently play different roles:

* **Pro Agent — Kimi:** looks for evidence supporting the claim.
* **Con Agent — DeepSeek:** looks for evidence against the claim.
* **Judge Agent — MiniMax:** compares both sides and makes the final decision.

### 4. Gonka Verification

All AI model requests are routed through the **Gonka Router**.

Each successful request produces a unique **Gonka Request ID**, allowing the AI inference process to be traced and verified.

### 5. Final Verdict

The system combines the three-agent results into a final verdict:

**TRUE · FALSE · MISLEADING · UNVERIFIED**

It also generates a **Truth Score from 0–100** and a confidence score.

### 6. Understand the Result

The result includes:

* Final conclusion
* Truth Score
* Confidence
* Pro / Con / Judge summaries
* Evidence and references
* Reasoning metrics
* Risk warnings
* Model request IDs

Metrics include factual accuracy, source quality, logical consistency, neutrality, temporal consistency, and model consensus.

## ⛓️ On-Chain Proof

Once a verification is eligible, the result can be permanently attested on **Arbitrum Sepolia**.

The system creates a cryptographic hash of the claim and prepares the verification evidence for **IPFS**.

You can connect an EVM wallet such as MetaMask and submit the result to the **TruthRegistry** smart contract.

The on-chain record stores the claim hash, Truth Score, verdict, Gonka Request IDs, IPFS metadata, attester, and timestamp.

After the transaction is confirmed, anyone can verify the attestation from the blockchain.

## 📊 Live Dashboard

The application can also display recent on-chain fact-checking attestations directly from the TruthRegistry contract.

This makes verified results transparent and publicly traceable.

## 💡 Why It Matters

GONKA AI Fact Checker combines:

**Multi-Agent AI Debate**

* **Gonka Inference Proof**
* **Evidence & Reasoning**
* **IPFS Storage**
* **Blockchain Attestation**

The goal is simple:

> **Don't just tell people what is true. Show them why — and let them verify the proof.**
