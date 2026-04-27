# ai-pr-audit

> GitHub App that flags AI-specific anti-patterns in pull requests.

ai-pr-audit reviews pull requests for failure modes that LLM-generated code produces but humans rarely do — hallucinated imports, made-up function signatures, AI-typical security blind spots. Less noise than generic AI code reviewers, sharper signal.

**Status**: pre-release scaffold. Not yet functional.

## Why

Generic AI code reviewers (CodeRabbit, Greptile) review every line of every PR. ai-pr-audit is narrower: it flags only the patterns that distinguish AI-generated code from human code. The wedge is signal-to-noise — fewer comments, each one actionable.

## License

[MIT](LICENSE) — by [@verepdev](https://github.com/verepdev).
