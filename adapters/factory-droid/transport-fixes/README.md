# WorkBuddy HTTP status correction

Droid acceptance on 2026-10-12 exposed a shared model-transport defect outside
Backpack's Python package. The installed WorkBuddy adapter changed upstream
HTTP 429 into local HTTP 502. The retained error body length and SHA-256 exactly
matched the adapter's sanitized `WB_CHAT_HTTP_429` response. The original vendor
body and Retry-After were not retained, so rate limiting and quota exhaustion
cannot be distinguished retrospectively.

`workbuddy-http-status.patch` preserves explicit chat/catalog upstream 4xx/5xx
status codes. Network and incomplete-stream uncertainty retains the existing
handling. Credentials, free-model validation, retry/fallback policy and Backpack
execution permissions are unchanged. This shared runtime is used by other hosts
too; this folder records the Droid-discovered fix and does not install it as part
of the Backpack wheel.

Run the transport regression against a chosen installed or candidate module:

```sh
TEST_WORKBUDDY_MODULE=/absolute/path/workbuddy_upstream.mjs node --test test_workbuddy_http_status.mjs
```

The 13 tests use a local HTTP server and injected responses. They send no vendor
requests and cover status preservation, one-send behavior, private error-body
exclusion, network uncertainty and successful output. The original module failed
9 tests; the patched installed module passed all 13. Existing router regression
also passed 12 tests.

Live Droid acceptance used its existing daily Backpack 0.3.0 connection and five
new requests through the configured free route, with all five protocol-complete.
The original completed MCP query was not executed again. Droid produced its
missing final answer from the verified stored result, with zero tool calls.
Then one real Backpack acquire selected and delivered the report Skill through
two directory levels; Droid applied its unique guidance. Invoke was disabled and
verified absent from the admitted native tool inventory for the continuation.

The original interrupted SQL attempt remains a failed historical attempt; its
recovery is not a fresh uninterrupted MCP end-to-end run. The vendor's original
429 cause remains unobservable. See `docs/capability-integration.md` for results
and the local evidence directory. Factory's documented session/tool/result
boundaries: <https://docs.factory.com/sdk/typescript>.
