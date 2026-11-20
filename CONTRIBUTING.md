# Contributing to the OTAS Cross-Rail DvP

Thanks for your interest in **OTAS Cross-Rail DvP**, part of the **Open Tokenized Asset Standard (OTAS)**. This repository makes the [OTAS whitepaper](https://github.com/OpenTokenizedAssetStandard/whitepaper) testable: machine-readable schemas for each seam, rail-neutral conformance vectors, verifier tooling, and whitepaper Flow A: cross-rail delivery-versus-payment, run as a simulation. The EVM leg also has Solidity contracts with Foundry tests; the Sui leg is simulated only for now. It is developed in the open under the **OTAS Lab at LF Decentralized Trust (LFDT)**.

Everything here is a proposal for community review. The schemas and reason codes are candidates for the standard, not adopted specifications.

New here? Start with these:

- 📖 **[Read the whitepaper (v0.2)](https://github.com/OpenTokenizedAssetStandard/whitepaper/blob/whitepaper-v0.2/whitepaper.md)**
- 👋 **[Introduce yourself in the welcome discussion](https://github.com/OpenTokenizedAssetStandard/whitepaper/discussions/7)**
- 🧪 **Run the simulated demo** — three commands, see the [README](./README.md#quickstart)

---

## Code of Conduct

This project follows a [Code of Conduct](./CODE_OF_CONDUCT.md) based on the LF Decentralized Trust community standards. By participating, you agree to uphold it.

---

## Ways to contribute

- **Add a rail.** A simulated adapter plus passing conformance vectors for Solana Token-2022, Hyperledger Fabric / Panurus, Besu, or Corda is the most valuable contribution right now. The UTXO model is the most likely to break our assumptions, which is exactly why we want it.
- **Add conformance vectors.** Every reason code and behaviour should have a rail-neutral vector.
- **Propose schema or reason-code changes,** with the motivation and the vectors that go with them.
- **Port the contracts to Sui Move.** The Sui leg is simulated only today; a Move package with tests would let both legs run on real chains.
- **Review the contracts.** They are unaudited research code; careful eyes are welcome.
- **Improve docs, scripts and CI.**

### Where to raise what

- **Questions about the standard itself** — what OTAS should specify — belong in the **[whitepaper Discussions](https://github.com/OpenTokenizedAssetStandard/whitepaper/discussions)**.
- **Questions this repository surfaces,** bugs, and concrete work belong in **[issues here](https://github.com/OpenTokenizedAssetStandard/cross-rail-dvp/issues)**.

When you open an issue you'll be offered templates: **🐛 Bug report**, **📐 Schema or reason-code change**, **🧪 Conformance vector**, **🔗 Rail adapter**, **❓ Open question**, and **⚙️ Repository / tooling**. Please search existing issues first.

---

## Development setup

Clone with submodules — the EVM tests depend on [forge-std](https://github.com/foundry-rs/forge-std), pinned as a submodule:

```bash
git clone --recurse-submodules https://github.com/<your-username>/cross-rail-dvp.git
```

What you need depends on what you touch:

| Area | Path | Tools |
|---|---|---|
| Schemas, conformance, simulated demo | `schemas/`, `conformance/`, `tools/`, `demo/` | Python 3.10+, `pip install -r requirements.txt` |
| EVM contracts | `live/evm/` | [Foundry](https://book.getfoundry.sh/) |

### Running the checks (the same ones CI runs)

```bash
# schemas, conformance vectors, simulated demo
pip install -r requirements.txt
cd tools
python -m otas_tools.cli validate-all
python -m otas_tools.cli run-vectors
python ../demo/run_demo.py
python -m otas_tools.cli reconcile ../demo/event_log.json

# EVM contracts
cd live/evm && forge test
```

---

## Rules for changes

- **Reason codes are additive.** Codes in `schemas/reasons-v1.json` are deprecated, never removed or renumbered, so a code recorded today still resolves when read back later.
- **Schema changes come with vectors.** A new behaviour, field or code arrives with the conformance vectors that exercise it.
- **Contract changes come with tests.** Changes under `live/evm/` come with Forge tests that pass in CI.
- **Keep both rails in step.** A reason code enforced on one rail should mean the same thing on the other, and the conformance vectors should prove it.
- **Never commit keys.** Test networks only.

---

## Making changes (pull request workflow)

Changes are proposed through pull requests from your own fork.

> **Please discuss before opening a pull request.** For anything beyond a small fix, raise it first in an [issue](https://github.com/OpenTokenizedAssetStandard/cross-rail-dvp/issues) and get rough agreement on the approach before you start.

Replace `<your-username>` with your GitHub username. `main` is the default development branch.

### 1. Fork the repository

Open https://github.com/OpenTokenizedAssetStandard/cross-rail-dvp and click **Fork**.

### 2. Clone your fork, with submodules

```bash
git clone --recurse-submodules https://github.com/<your-username>/cross-rail-dvp.git
cd cross-rail-dvp
```

### 3. Add the `upstream` remote

```bash
git remote add upstream https://github.com/OpenTokenizedAssetStandard/cross-rail-dvp.git
```

### 4. Set your Git identity (first time only)

Your commits must match your DCO sign-off. Use an email **verified on your GitHub account**:

```bash
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 5. Create a branch

```bash
git fetch upstream
git checkout -b feat/solana-adapter upstream/main
```

### 6. Make your change, and run the checks for the areas you touched

### 7. Commit with a DCO sign-off

```bash
git add .
git commit -s -m "feat(tools): add simulated Solana Token-2022 rail adapter"
```

> If upstream changes while you work, catch up with `git pull --rebase upstream main`.

### 8. Push and open the pull request

```bash
git push origin feat/solana-adapter
```

Open the PR against `OpenTokenizedAssetStandard/cross-rail-dvp`, targeting `main`. Fill in the template and link the issue — `Closes #123` or `Refs #123`.

### 9. Respond to review

Commit to the same branch and push again; sign off every commit. All checks, including DCO, must pass before a maintainer can merge.

---

## Developer Certificate of Origin (DCO)

All commits **must be signed off**, certifying you have the right to contribute the change ([what the DCO is](https://developercertificate.org/)):

```bash
git commit -s -m "Your commit message"
```

The sign-off name and email must match your commit author identity, and the email should be verified on your GitHub account. Forgot to sign off? `git commit --amend -s --no-edit` fixes the last commit (add `--reset-author` if the identity was also wrong).

---

## Commit messages

- Write in the **imperative mood**: *"Add HTLC refund test,"* not *"Added…"*.
- Keep the subject line short (about 50–72 characters) and explain the *why* in the body.
- Use [Conventional Commits](https://www.conventionalcommits.org/) with a scope: `feat(sui):`, `fix(runner):`, `test(evm):`, `docs:`, `ci:`, `build:`. Scopes in use: `schemas`, `tools`, `conformance`, `demo`, `evm`, `sui`, `runner`, `scripts`.

---

## Licensing

Code in this repository is licensed under **[Apache-2.0](./LICENSE)**. By contributing, you agree your contributions are licensed under the same terms; you retain copyright. The Lab charter intends specification material for the Community Specification License 1.0 — how that applies to `schemas/` is an open question tracked in the issues.

Referenced third-party code keeps its own terms: [forge-std](https://github.com/foundry-rs/forge-std) is a git submodule, not a copy.

---

## Security

Found a vulnerability? Please report it privately — see [SECURITY.md](./SECURITY.md).

---

## Community & getting help

- **Design questions about the standard?** [Whitepaper Discussions](https://github.com/OpenTokenizedAssetStandard/whitepaper/discussions).
- **Community calls.** OTAS holds regular open community calls; everyone is welcome.
- **Stuck on a contribution?** Comment on the relevant issue and a maintainer will help.

Thank you for helping build OTAS. 🚀
