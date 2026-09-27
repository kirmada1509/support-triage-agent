# Sandbox kit

Everything needed to turn the OpenTelemetry Astronomy Shop into the sandbox the agent
investigates: a fork pinned to release 3.1.0, four planted bugs tagged `v1.4.0` on top of a good
`v1.3.0`, one image per service and tag, and scenarios that reproduce each demo ticket.

The fork lives next to this repo (`../opentelemetry-demo`, or `SANDBOX_DIR`). This folder holds
what the fork is built from, so the fork itself never needs pushing anywhere, and this repo holds
the answers (which commits are bugs) where the codebase analyst can't read them.

```text
sandbox/
  upstream.env        upstream URL and pinned commit; the tag SHAs setup.sh should produce
  overlay/            files the fork owns, committed first:
    compose.versions.yaml   each versioned service's image and service.version, from versions.env
    compose.extras.yaml     fewer load-generator users (trace retention), Jaeger's cap and memory
    .env.override           pins every other service to the 3.1.0 release images
  patches/v1.3.0/     the read-only agent_ro role in src/postgresql/init.sql
  patches/v1.4.0/     8 commits: the 4 planted bugs mixed with 4 harmless ones
  setup.sh            clone, pin, overlay, patches, tags
  build-images.sh     sandbox/<service>:<tag> for payment, quote, checkout, product-catalog
  compose.sh          docker compose with the shop's minimal-mode files + compose.versions.yaml
```

## Run it

Needs Docker with about 4 GB free for the shop (it uses ~2.5 GB at rest), and this repo's Postgres
(`make db && make migrate`), where deploys and flag changes are recorded.

```bash
make sandbox          # clone into ../opentelemetry-demo, apply the kit, tag v1.3.0 and v1.4.0
make sandbox-images   # 8 images, a few minutes the first time; skips images already built
make shop-up          # minimal mode: 25 containers, every versioned service on v1.3.0
make scenario-4       # reproduce ticket 4 and send it (make api must be running)
```

The shop is at http://localhost:8080, Jaeger at http://localhost:8080/jaeger/ui, Grafana at
http://localhost:8080/grafana, Prometheus at http://localhost:9090. `make shop-down` stops it and
deletes its volumes. Run from a worktree of this repo, set `SANDBOX_DIR` to the fork's path.

`make deploy s=payment v=v1.4.0` switches one service and records the deploy with its commit
titles; `make flag f=paymentFailure v=25%` changes a flag and records it. `versions.env` in the
fork says what's running.

## The planted bugs

Lines are at `v1.4.0`. Each commit changes behaviour on a path the storefront or load generator
really uses, and none of the messages says what it breaks.

| Bug | Where | Commit | What the data shows | Reproduce |
| --- | --- | --- | --- | --- |
| Cards rejected in their expiry month | `src/payment/charge.js:88`, `>` became `>=` inside a refactor | refactor: simplify card expiry comparison | payment `charge` spans at `service.version=v1.4.0` fail with "The credit card (ending 4242) expired on 9/2026." only for cards expiring this month | `make scenario-4` |
| Shipping doubled above 10 items | `src/quote/app/routes.php:34-39`, batches added to a `$quote` that already holds the total | perf: batch quote calculation for large orders | `calculate-quote` spans: `demo.shipping.quote.cost.total` / `items_count` is 17.98 above 10 items, 8.99 at or below | `make scenario-5` |
| Items stay in the cart after a non-USD order | `src/checkout/main.go:544-554`, early return before `emptyUserCart` | chore: tidy up post-order cleanup | EUR and CAD orders have no checkout `EmptyCart` span; the cart still holds the items | `make scenario-8` |
| The Comet Book ($0.99) missing from the listing | `src/product-catalog/main.go:235`, `WHERE p.price_units > 0` | feat: hide unpriced products from the catalog listing | `ListProducts` spans' `demo.product.count` drops from 10 to 9; `catalog.products` still has 10 rows, the missing one with `price_units = 0, price_nanos = 990000000`; its product page still works | `make scenario-9` |

The harmless commits: payment's README gains the charge rules (including "a card stays valid
through the last day of its expiration month", which the expiry bug contradicts), checkout and
quote logs gain a field each, and payment's declined-charge log gains the message "Charge
declined.". The Amex decline (ticket 3) is upstream's own card-type rule at `charge.js:82-84`,
unchanged since before `v1.3.0`.

The plan's case-sensitive search bug was dropped: nothing in the shop calls `SearchProducts`, so
no customer could notice it.

## Scenarios

`scenarios/scenario.py` places orders through the frontend API the way the load generator does,
each with its own trace ID, then checks in Jaeger that the bug really reproduced. It exits 1 and
sends nothing if it didn't. Bug scenarios reset the service to `v1.3.0` first without recording
it, place baseline orders, wait `--gap` seconds (default 60) so the change stands apart in
the metrics, deploy `v1.4.0` (recorded), then place the same orders again (`--rounds`, default 3).
The ticket goes out with the real times in it (`--no-send` prints it instead).

| Scenario | Shoppers | What it does |
| --- | --- | --- |
| `3` Amex false positive | 07 (Amex ending 0005), 08 (Visa) | 3 declined Amex checkouts and one Visa that goes through; no deploy |
| `4` expiry bug | 03, 11, 04, 12 (expire this month), 05, 13 (later) | this month's cards pass on v1.3.0 and fail on v1.4.0; later ones pass on both |
| `5` bulk shipping | 15 (20 items), 16 (24 items), 17 (2 items) | shipping per item goes from $8.99 to $17.98 above 10 items only |
| `6` paymentFailure flag | 18, 19, 20 | 6 orders with the flag off, flag to 25% (recorded), 24 orders of which about a quarter fail. Leaves the flag on: `make flag f=paymentFailure v=off` afterwards |
| `8` (or `cart`) | 01 (EUR), 02 (CAD), 09 (USD) | non-USD carts keep their items on v1.4.0 |
| `9` (or `catalog`) | none | The Comet Book drops out of `/api/products` on v1.4.0 |
| `1`, `2`, `7` | none | just send the ticket; send 7 after ticket 4's verdict is recorded |

Shoppers are the Figma Merch tenant's (`figma-shopper-01` to `-20`); the load generator's
traffic uses random IDs and belongs to no tenant. Checkout puts `user.id` on its `PlaceOrder`
span, which is how the data analyst finds one tenant's orders.

## Tests

| Command | Needs | Checks |
| --- | --- | --- |
| `make test` | nothing | each scenario against a simulated shop: it passes with the bug and fails without it; the ticket text it sends; cards, payloads, signing; the kit's files agree with each other |
| `make test-sandbox` | the fork | tags at the expected SHAs, v1.3.0 is upstream plus the setup, each bug line blames to its planted commit, the Amex rule blames to upstream, the lines this README cites, the images' revisions |
| `make test-shop` | the running shop | every scenario for real (a few minutes), deploys recorded with their commits, `service_version` on span metrics, the daily log index, `agent_ro` can read but not write |

`make test-shop` records deploys into the throwaway `triage_test` database, not the dev one, and
turns the `paymentFailure` flag back off when it's done.

## Gotchas

- The shop's `.env` resolves `OTEL_RESOURCE_ATTRIBUTES` from its own `IMAGE_VERSION` before
  `.env.override` is read; the overlay restates it. `DEMO_VERSION=latest` has moved past 3.1.0,
  so the overlay pins it.
- Jaeger keeps traces in memory at about 50 KB each; 25000 traces fit its 1200M limit. Raise the
  cap and the memory together, or Jaeger restarts and every trace is gone.
- `flag.sh` edits `src/flagd/demo.flagd.json` in the fork, which leaves the fork dirty, and
  `make sandbox` then refuses to run: `git -C ../opentelemetry-demo checkout -- src/flagd`.
- A trace arrives in pieces (each service exports in batches): wait for the span you need
  (`Shop.spans(until=...)`) rather than the first response.
- The shop's clock is UTC; ticket times are the customer's local time.
- The frontend has no search box and nothing calls `SearchProducts`; don't build on search.

## Changing the fork

The fork is rebuilt from scratch on every `make sandbox`, with fixed authors, committer and dates,
so `v1.3.0` and `v1.4.0` get the same SHAs on every machine (`upstream.env` says which; setup.sh
warns if they differ). To change a planted commit, edit it in the fork (for example with
`git rebase -i v1.3.0`), then export the series again and update the SHAs in `upstream.env`:

```bash
cd ../opentelemetry-demo
git format-patch --zero-commit --no-signature -o ../support-triage-agent/sandbox/patches/v1.4.0 v1.3.0..v1.4.0
```

Delete the old patch files first if the commit titles changed. `make sandbox` refuses to run while
the fork has uncommitted changes; `flag.sh` leaves one in `src/flagd/demo.flagd.json`, which
`git checkout -- src/flagd` undoes.

The read-only role: `agent_ro` / `agent_ro_password` on `astronomy-db:5432/astronomy_db` can
`SELECT` from the `catalog` schema and nothing else; its transactions are read-only and time out
after 5 seconds.
