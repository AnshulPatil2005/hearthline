/** A gift card's public link. It's what the QR code holds: the business scans it, the buyer checks the balance. */
export const cardUrl = (code: string) => `${window.location.origin}/card/${encodeURIComponent(code)}`

/** A scanned QR code (a card link) or a typed code, as the code alone. */
export const codeFrom = (value: string) => decodeURIComponent(value.trim().split('/card/').pop() ?? value).toUpperCase()
