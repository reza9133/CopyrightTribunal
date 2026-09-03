# Copyright Tribunal Intelligent Contract

A decentralized, AI-native arbitration system built on **GenLayer** for detecting and resolving copyright infringement and plagiarism disputes automatically through multi-validator consensus.

## Overview

Smart contracts traditionally lack the ability to read unstructured text from live web sources or exercise judgment on subjective matters like creative similarity. **Copyright Tribunal** leverages GenLayer's **Intelligent Contracts** and **Optimistic Democracy** to bridge this gap. 

This contract allows creators to register digital assets, file plagiarism disputes with suspected URLs, and trigger a decentralized AI adjudication process that fetches live web evidence, evaluates structural and semantic similarity, and issues a binding verdict without trusted oracles.

## Key Features

- **Native Web Fetching**: Directly retrieves live web documents via `gl.nondet.web.get()` from standard HTTPS URLs.
- **Content Integrity Protection (Anti-Tamper)**: Programmatically verifies the SHA-256 hash of the registered content during adjudication, automatically clearing claims if the original source has been altered.
- **AI-Driven Adjudication**: Integrates Large Language Models (LLMs) via `gl.nondet.exec_prompt()` to compare content and determine plagiarism percentages.
- **Deterministic Verdict Enforcement**: Programmatically enforces the final verdict rule based on similarity scores, eliminating AI hallucinations on settlement logic.
- **Robust Consensus (`run_nondet_unsafe`)**: Implements custom validator logic with numeric tolerance (±5%) and exact verdict matching to prevent consensus failures caused by minor LLM output variations.
- **Safe JSON Normalization**: Includes defensive text parsing to clean model outputs and eliminate malformed JSON errors.

## Contract Architecture & Lifecycle

1. **Asset Registration (`register_asset`)**: The copyright owner registers an asset ID along with its original source URL and content hash.
2. **Filing a Dispute (`file_dispute`)**: A claimant registers a dispute case against a registered asset by providing the URL containing suspected plagiarized content.
3. **Adjudication (`adjudicate_dispute`)**: 
   - Network validators independently fetch both the original and claimant web documents.
   - **Content Hash Verification**: Programmatically recalculates the SHA-256 hash of the original document and compares it against the registered `content_hash` to prevent tampering.
   - **AI Arbitration & Rule Enforcement**: An LLM analyzes and compares the text to evaluate similarity, and the contract programmatically enforces the final verdict (`INFRINGEMENT_FOUND` if score > 30, otherwise `CLEARED`).
   - **Consensus Validation**: Validators execute cross-verification checks to reach consensus within a strict $\pm5\%$ score tolerance.

## Code Structure

- **`CopyrightAsset` & `DisputeCase`**: Persistent storage structures decorated with `@allow_storage` using typed fields (`Address`, `u32`, `u8`, `TreeMap`).
- **`_fetch_document`**: Handles non-deterministic HTTP requests and safety checks.
- **Hash Verification & Rule Enforcement**: Combines cryptographic integrity checks (`hashlib.sha256`) with deterministic rule enforcement.
- **`leader_fn` & `validator_fn`**: Encapsulates the leader execution and multi-validator cross-verification logic required by GenLayer's Optimistic Democracy.

## Requirements

- Python 3.12+
- GenVM SDK (`genlayer`)
- GenLayer Studio or Testnet Bradbury/Asimov environment

## Deployment & Testing

1. Load the contract into [GenLayer Studio](https://studio.genlayer.com) or your local environment.
2. Deploy the contract (no constructor parameters are required). **Deployed Contract Address:** `0x0fFC88Be6A6c5fCC38BC29Aaf7B477aeF4443bB7`
3. Execute write methods sequentially:
   - Call `register_asset` with your asset ID, verified HTTPS URL, and content hash.
   - Call `file_dispute` to link a suspected URL.
   - Call `adjudicate_dispute` to run the decentralized AI consensus audit.

## License

This project is open-source and available under the MIT License.
