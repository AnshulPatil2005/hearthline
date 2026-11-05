# Hearthline Public API: SDKs and portal (APIMatic)

This folder is the [APIMatic](https://www.apimatic.io) build input for Hearthline's Public API v1. It produces
SDKs in TypeScript, Python and C# and an API documentation portal.

```
apimatic/src/
  apimatic.json                      portal and SDK settings (languages, package names, brand, links)
  spec/hearthline-v1.openapi.json    the API, generated from the FastAPI code
  content/toc.yml                    the portal's table of contents
  content/guides/                    hand-written guides: giving through PayPal, using the MCP server
```

The spec is never edited by hand. `uv run python -m scripts.export_api` (in `backend/`) writes it here and to
[`docs/api`](../docs/api), and a test fails if either copy is out of date with the code
([`test_api_contract.py`](../backend/tests/test_api_contract.py)), which also checks that every operation has an id
and a description for the SDKs.

## Build

With the [APIMatic CLI](https://www.npmjs.com/package/@apimatic/cli) and an APIMatic API key:

```bash
npx @apimatic/cli@2 auth login --auth-key=$APIMATIC_API_KEY
npx @apimatic/cli@2 api validate -i apimatic
npx @apimatic/cli@2 sdk generate -l typescript -i apimatic -d apimatic/sdk/typescript
npx @apimatic/cli@2 sdk generate -l python -i apimatic -d apimatic/sdk/python
npx @apimatic/cli@2 sdk generate -l csharp -i apimatic -d apimatic/sdk/csharp
npx @apimatic/cli@2 portal generate -i apimatic -d apimatic/portal
```

The [APIMatic workflow](../.github/workflows/apimatic.yml) runs the same steps on GitHub when the
`APIMATIC_API_KEY` repository secret is set, and attaches the SDKs and the portal to the run.

## Using an SDK

Every operation is public and needs no key. Preparing a gift returns a PayPal approval link; a person approves
the payment on PayPal, so an SDK can never charge anyone. See the
[giving guide](src/content/guides/give-through-paypal.md).
