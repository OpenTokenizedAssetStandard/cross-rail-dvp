# OTAS Cross-Rail DvP

[![LFDT Lab](https://img.shields.io/badge/LF%20Decentralized%20Trust-Lab-blue)](https://www.lfdecentralizedtrust.org/)  [![Status: experimental](https://img.shields.io/badge/status-experimental-orange)](#status)  [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](./LICENSE)  [![CI](https://github.com/OpenTokenizedAssetStandard/cross-rail-dvp/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenTokenizedAssetStandard/cross-rail-dvp/actions/workflows/ci.yml)

**OTAS Cross-Rail DvP** makes the [Open Tokenized Asset Standard whitepaper](https://github.com/OpenTokenizedAssetStandard/whitepaper) testable: machine-readable schemas for the seams the draft identifies, rail-neutral conformance vectors and verifier tooling, and runnable versions of the whitepaper's reference flows.

OTAS is a lab under [LF Decentralized Trust (LFDT)](https://www.lfdecentralizedtrust.org/).

<a id="status"></a>

> **Status: experimental.** Research and educational artifacts under the OTAS Lab charter. The schemas and reason codes are proposals for community review, not adopted specifications. The contracts are unaudited and target test networks only.

## Quickstart

Needs only Python:

```bash
pip install -r requirements.txt
cd tools
python -m otas_tools.cli validate-all     # schemas parse, reason registry lints clean
python -m otas_tools.cli run-vectors      # same fixture -> same reason code on every rail
```

## Schemas

The artifacts in [`schemas/`](./schemas) are this repository's candidate for the standard's normative surface. Each one maps to a section of the [whitepaper (v0.2)](https://github.com/OpenTokenizedAssetStandard/whitepaper/blob/whitepaper-v0.2/whitepaper.md).

| File | Defines | Whitepaper |
|---|---|---|
| `reasons-v1.json` | The reason-code registry: coarse, additive codes a `canTransfer` check returns | §6.3 |
| `manifest.schema.json` | The capability manifest, including whether each behaviour is chain-observed or issuer-declared | §5.2, §5.4 |
| `events.schema.json` | The canonical event envelope, with the finality model and moment declared per event | §5.2, §6.1 |
| `settlement.schema.json` | The settlement instruction: `Proposed → Committed → Settled \| Aborted`, with per-leg finality | §6.1 |
| `core-descriptor.schema.json` | The asset metadata envelope, including the settlement-asset tier | §6.4, §7 |

Where the draft leaves a question open, the schemas make a concrete choice and say so in their descriptions.

## Tooling and conformance

[`tools/otas_tools`](./tools/otas_tools) provides one small verifier per seam, in the spirit of [otas-probe](https://github.com/vishnugovind10/otas-probe):

| Command | Checks |
|---|---|
| `validate-all` | Every schema parses; the reason registry passes its lint |
| `lint-reasons` | Unique names and numbers, additivity, coarse wire codes |
| `check-manifest FILE` | Manifest validity, native/observed provenance, anchors, exclusions |
| `run-vectors` | [`conformance/vectors.json`](./conformance/vectors.json) against every simulated rail |
| `reconcile FILE` | Any event log, simulated or live: schema validity, atomicity, declared finality |

**Conformance-first.** The vectors, not any one implementation, define what conformant means: a rail is conformant when the same fixture produces the same reason code. Adding a ledger means writing one adapter and passing the same vectors.

## Contributing

Contributions are welcome — new rails, conformance vectors, schema proposals, reviews of the contracts, and runs on testnet. See the [contribution guidelines](./CONTRIBUTING.md) and the [Code of Conduct](./CODE_OF_CONDUCT.md). All commits must be signed off under the Developer Certificate of Origin (DCO). Questions about the standard itself belong in the [whitepaper Discussions](https://github.com/OpenTokenizedAssetStandard/whitepaper/discussions).

## License

Licensed under [Apache-2.0](./LICENSE). Referenced third-party code keeps its own terms: [Mysten Labs' PAS](https://github.com/MystenLabs/pas) and [forge-std](https://github.com/foundry-rs/forge-std) are git submodules, not copies.
