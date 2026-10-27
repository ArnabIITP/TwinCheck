# TwinCheck synthetic stateful corpus v1

This is a deterministic correctness fixture, not a performance benchmark or a claim that TwinCheck outperforms another tool. It exercises a versioned request sequence, prerequisite ordering, reset-health assertions, differential comparison, portable regression-pack export, and replay.

## Run it

Install from the repository root with `python -m pip install -e .`. Start two services in separate terminals:

```bash
python examples/stateful_cart_service.py --port 8001
python examples/stateful_cart_service.py --port 8002 --total-delta 1
```

Execute the corpus:

```bash
twincheck compare-http-sequence \
  --reference-url http://127.0.0.1:8001 \
  --candidate-url http://127.0.0.1:8002 \
  --sequence benchmarks/stateful-corpus-v1/sequence.json \
  --reset-sequence benchmarks/stateful-corpus-v1/reset-sequence.json \
  --contract benchmarks/stateful-corpus-v1/contract.json \
  --repeat 2 --timeout 3 \
  --output reports/stateful-corpus-v1.json \
  --junit reports/stateful-corpus-v1.xml
```

Expected exit status: `1`, because the candidate deliberately adds one to the cart total. The reset endpoint returns 2xx, and the separate GET health contract asserts `/body/item_count == 0` before each repeat.

Export and replay the finding:

```bash
twincheck export-http-sequence-pack --report reports/stateful-corpus-v1.json --output reports/stateful-cart-pack
twincheck replay-http-sequence-pack --pack reports/stateful-cart-pack \
  --reference-url http://127.0.0.1:8001 --candidate-url http://127.0.0.1:8002 \
  --allow-side-effects --output reports/stateful-corpus-v1-replay.json
```

Replay requires explicit acknowledgement because the saved sequence may mutate local state.

## Negative control: a misleading 200 reset

Start a service with stale state and a deliberately broken reset endpoint:

```bash
python examples/stateful_cart_service.py --port 8003 --broken-reset --initial-item-quantity 99
```

Use it as either comparison target with the checked-in reset sequence. The endpoint returns 200, but TwinCheck must stop before sending the tested workflow because the health assertion fails.

## Reproducibility record

- Corpus version: `1`; baseline sequence is fixed and needs no random seed.
- Target fixture: `examples/stateful_cart_service.py`, an in-memory service bound to loopback.
- Repeat count: `2`; request timeout: `3` seconds.
- Response retention uses the stateful HTTP adapter cap of `100000` bytes.
- No performance statistics or cross-tool superiority claims are made.
- Blind spots: one small cart workflow and one injected total mismatch; no database, concurrency, distributed state, full authentication or real-world service coverage. A health contract proves only its assertions, not every hidden state variable.
- Supported CI interpreters: Python 3.11, 3.12 and 3.13. Record commit SHA, OS, Python version, exact commands and fixture hashes for reproducibility.
