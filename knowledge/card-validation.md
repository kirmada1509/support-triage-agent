# Card validation

## Invalid number

Payment validates the card number before checking its type or expiry. An invalid-number result differs from a supported card failing later.

## Unsupported type

After number validation, only Visa and Mastercard pass the card-type rule. Amex failure is expected unless that policy changes.
