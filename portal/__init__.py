"""MIRAGE control/monitoring portal — a thin web UI over the run artifacts + ledger.

`portal.data` reads the backend artifacts and shapes them into the API responses;
`portal.server` is a dependency-free stdlib HTTP server that exposes them as JSON and
serves the (unstyled-logic, design-skinned) single-page frontend under `portal/static`.
"""
