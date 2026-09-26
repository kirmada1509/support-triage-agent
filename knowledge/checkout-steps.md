# Checkout stages

## Order flow

Checkout fetches cart items, prices them, gets a shipping quote, charges the card, and requests shipment. A failure can occur at several stages.

## Successful response

A completed order result contains an order ID, tracking ID, shipping cost, address, and items. Ask for the order ID when distinguishing a completed order from an attempt.
