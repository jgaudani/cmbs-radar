"""Opportunity briefs written by Claude. The model only writes: every number
and the classification come from scoring and are passed in as facts, and the
prompt forbids new calculations."""

from __future__ import annotations

import json

import anthropic

PROMPT_VERSION = "brief-v1"  # part of the cache key: bump when the prompt changes
DEFAULT_MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You write one-page opportunity briefs for commercial real estate brokers at Newmark.

You receive FACTS as JSON about one CMBS loan: collateral, loan terms, the refinance sizing computed by Newmark's scoring engine, risk flags, recent changes, and the Newmark team the opportunity is routed to. Write the brief from those facts only.

Rules:
- Use only numbers that appear in FACTS, formatted as they appear or rounded (e.g. $1.08B, 41%, 1.77x). Never calculate, estimate, or infer a number that is not in FACTS. If something a broker would want is missing, say it is not reported.
- Do not change or second-guess the classification or the routing; explain them.
- Borrower names are not disclosed in CMBS data. Do not guess owners, sponsors, or tenants beyond the tenant names in FACTS.
- When FACTS says the whole loan is an estimate (split across trusts), the financials are annualized from a partial year, or they come from underwriting at securitization, say so plainly where you use those numbers.
- Write for a busy broker: plain, specific, no hype, no filler.

Format (Markdown, under 300 words):
**<Property name>, <City, State>** on the first line.
Then four short sections with bold headings: **Situation**, **Why now**, **The opportunity** (what the routed Newmark team could offer, grounded in the gap and flags), **Watch-outs** (data caveats and risks from FACTS)."""


class RefusedError(Exception):
    """The model declined (stop_reason "refusal") even after the fallback."""


class MissingCredentialsError(Exception):
    pass


class Generator:
    def __init__(self, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model or DEFAULT_MODEL
        self._client = client

    def _get_client(self) -> anthropic.Anthropic:
        # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth
        # login` profile; created lazily so the api starts without one.
        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
            except Exception as e:  # no credential source at all
                raise MissingCredentialsError(str(e)) from e
        return self._client

    def write(self, facts: dict) -> tuple[str, str]:
        """The brief for facts and the model that produced it (a fallback
        model if the first one declined)."""
        client = self._get_client()
        try:
            resp = client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": "FACTS:\n" + json.dumps(facts, indent=2, default=str)}],
                output_config={"effort": "medium"},
                # If a safety classifier declines, the server re-serves the
                # request on a fallback model chosen by refusal category.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise MissingCredentialsError(str(e)) from e
        if resp.stop_reason == "refusal":
            raise RefusedError("model declined to write this brief")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise RuntimeError(f"claude returned no text (stop reason {resp.stop_reason})")
        return text, resp.model
