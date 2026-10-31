# Verification records

These are real qwen3.8-27b calls over the original fictional Cedar PDF.

- positive-run.json: identifier, count, limitations; actual local tools and page citations.
- unsupported-run.json: the source does not provide a score improvement percentage.
- test-results.txt: local regression test outcome; these tests do not call a real model.

API credentials and private user documents are excluded. A valid citation establishes the returned page, not semantic correctness.

Additional current-interface report evidence:
- report-tool-run.json: 15.71 seconds, 3 tool calls, original identifier/count.
- report-unsupported-run.json: 20.77 seconds, 8 tool calls, source does not provide a score improvement percentage.
