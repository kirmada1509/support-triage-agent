# Checkout error categories

## Payment failure

A card decline appears as a 422 payment-failed response. This label is a category, not the underlying payment reason.

## Order failure

Other place-order failures appear as generic checkout errors. Inspect the checkout trace to find whether cart, pricing, shipping, or another stage failed.
