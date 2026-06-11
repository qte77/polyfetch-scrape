"""Detector unit tests. Pure functions: Response in, list[Finding] out — no network."""

import pytest

from polyfetch_scrape.contrib.easter_hunt.detectors import (
    html_comments,
    weird_headers,
    wellknown_present,
)
from polyfetch_scrape.response import Response


def _html(body: bytes, url: str = "https://example.com/") -> Response:
    return Response(
        url=url, status=200, headers={}, body=body, content_type="text/html", backend="httpx"
    )


def _with_headers(headers: dict[str, str], url: str = "https://example.com/") -> Response:
    return Response(
        url=url, status=200, headers=headers, body=b"", content_type=None, backend="httpx"
    )


# --------------------------------------------------------------------------- #
# html_comments
# --------------------------------------------------------------------------- #


def test_html_comments_empty_body_returns_empty_list() -> None:
    # Exercises the decode -> finditer pipeline on a zero-byte body: a naive impl
    # that calls match.group() without a match guard would raise here.
    assert html_comments(_html(b"")) == []


def test_html_comments_body_without_comments_returns_empty_list() -> None:
    body = b"<html><head></head><body><p>Hello</p></body></html>"
    assert html_comments(_html(body)) == []


def test_html_comments_unterminated_comment_is_silently_dropped() -> None:
    # A lazy `<!--([\s\S]*?)-->` requires the closing `-->`; an open-ended comment
    # yields no match. Guards the regex against a greedy variant that would capture
    # to end-of-body and emit a bogus finding.
    assert html_comments(_html(b"<!-- this comment never closes")) == []


def test_html_comments_recruiting_keyword_is_notable_with_fixed_confidence() -> None:
    body = b"<!-- We are hiring engineers! Visit /careers -->"

    findings = html_comments(_html(body))

    assert len(findings) == 1
    f = findings[0]
    assert f.detector == "html_comments"
    assert f.category == "recruiting"
    assert f.severity == "notable"
    assert f.location == "body:comment[0]"
    assert f.confidence == 0.9  # fixed for keyword match, NOT density-driven
    assert f.url == "https://example.com/"
    assert "hiring" in f.snippet


@pytest.mark.parametrize("word", ["hiring", "join", "recruiter", "careers"])
def test_html_comments_each_recruiting_keyword_triggers(word: str) -> None:
    # Each of the four stems (hir|join|recruit|career) must independently fire,
    # so a missing branch in the keyword set is caught per-word, not in aggregate.
    findings = html_comments(_html(f"<!-- {word} now -->".encode()))
    assert [f.category for f in findings] == ["recruiting"]


def test_html_comments_keyword_detected_past_snippet_truncation() -> None:
    # The keyword lives past char 120, so a Finding only appears if the keyword
    # check runs on the FULL comment text, not on the truncated snippet.
    body = b"<!-- " + b"x" * 130 + b" hiring -->"

    findings = html_comments(_html(body))

    assert len(findings) == 1
    assert findings[0].category == "recruiting"
    assert len(findings[0].snippet) == 120
    assert "hiring" not in findings[0].snippet  # proves snippet != detection surface


def test_html_comments_box_drawing_art_is_novelty_high_confidence() -> None:
    # Pure box-drawing art, no recruiting words: isolates the novelty branch and
    # its density-based confidence.
    body = "<!--\n ▄▓▓▓▓▓▄\n █▀╓╙█▀█\n ▄▄▄▄▄▄▄\n-->".encode()

    findings = html_comments(_html(body))

    assert len(findings) == 1
    f = findings[0]
    assert f.detector == "html_comments"
    assert f.category == "novelty"
    assert f.severity == "info"
    assert f.confidence >= 0.8


def test_html_comments_novelty_confidence_clamps_at_one() -> None:
    # 100% box-drawing density would compute density*8 = 8.0; must clamp to 1.0.
    findings = html_comments(_html("<!--▄▓█▀╓╙-->".encode()))
    assert findings[0].confidence == 1.0


def test_html_comments_low_box_density_is_below_novelty_threshold() -> None:
    # One box char in a long comment -> density 0.01 -> confidence 0.08 < 0.1.
    # Falls through to no-finding; guards the >=0.1 novelty gate (exclusion side).
    body = ("<!--▄" + " " * 99 + "-->").encode()
    assert html_comments(_html(body)) == []


def test_html_comments_novelty_threshold_inclusion_boundary() -> None:
    # One box char in a 10-char comment -> density 0.1 -> confidence 0.8 >= 0.1: emits.
    body = ("<!--▄" + " " * 9 + "-->").encode()
    findings = html_comments(_html(body))
    assert [f.category for f in findings] == ["novelty"]


def test_html_comments_recruiting_takes_priority_over_novelty() -> None:
    # Art that ALSO contains a recruiting word must classify as recruiting (higher
    # priority), not novelty. Proves ordering, not just that *some* finding fires.
    body = "<!-- ▄▓█▀╓╙ we are hiring ▄▓█▀╓╙ -->".encode()

    findings = html_comments(_html(body))

    assert len(findings) == 1
    assert findings[0].category == "recruiting"
    assert findings[0].confidence == 0.9


def test_html_comments_ie_conditional_suppressed_even_when_keyword_present() -> None:
    # STRENGTHENED: this comment contains "hir" and would fire as recruiting, but the
    # IE-conditional suppression must run BEFORE categorisation. A trivial `[if IE]`
    # fixture would return [] even with no suppression rule at all.
    assert html_comments(_html(b"<!--[if hiring]>enable old browser<![endif]-->")) == []


def test_html_comments_gtm_boilerplate_suppressed() -> None:
    body = b"<!-- Google Tag Manager -->\n<!-- End Google Tag Manager -->"
    assert html_comments(_html(body)) == []


def test_html_comments_begin_prefixed_recruiting_comment_is_not_suppressed() -> None:
    # Regression: generic "begin "/"end " prefixes must NOT suppress a real recruiting
    # easter egg; only GTM/gtag-specific prefixes are dropped.
    findings = html_comments(_html(b"<!-- Begin your career at Acme Corp -->"))
    assert [f.category for f in findings] == ["recruiting"]


def test_html_comments_plain_uncategorised_comment_yields_nothing() -> None:
    # Comment exists, not suppressed, no keyword, no art -> silent skip branch.
    assert html_comments(_html(b"<!-- just a normal authoring note -->")) == []


def test_html_comments_index_counts_suppressed_comments() -> None:
    # The suppressed comment at index 0 WOULD fire as recruiting ("hiring") if
    # suppression were broken; guards that it is dropped yet still consumes an index
    # slot, so the following recruiting comment is reported at index 1.
    body = b"<!--[if hiring]>x<![endif]--><!-- we are hiring -->"

    findings = html_comments(_html(body))

    assert len(findings) == 1
    assert findings[0].location == "body:comment[1]"
    assert "[if" not in findings[0].snippet


def test_html_comments_index_counts_uncategorised_comments() -> None:
    body = b"<!-- normal note --><!-- recruiting: join us -->"

    findings = html_comments(_html(body))

    assert len(findings) == 1
    assert findings[0].location == "body:comment[1]"


def test_html_comments_snippet_is_stripped_and_truncated_to_120() -> None:
    inner = "join " + "a" * 200
    body = f"<!--\n   {inner}\n-->".encode()

    snippet = html_comments(_html(body))[0].snippet

    assert len(snippet) == 120
    assert snippet.startswith("join a")  # leading whitespace/newline stripped first


def test_html_comments_decodes_non_utf8_bytes_without_raising() -> None:
    # Invalid UTF-8 bytes inside the comment must decode via errors="replace"
    # (-> U+FFFD), never raise; the box art still scores as novelty.
    body = b"<!--\xff\xfe" + "▄▓█▀╓╙".encode() + b"-->"

    findings = html_comments(_html(body))

    assert [f.category for f in findings] == ["novelty"]


def test_html_comments_url_is_taken_from_response() -> None:
    findings = html_comments(_html(b"<!-- hiring -->", url="https://acme.test/jobs"))
    assert findings[0].url == "https://acme.test/jobs"


def test_html_comments_snippet_strips_terminal_control_chars() -> None:
    # Untrusted comment bytes must not leak ANSI/control chars into the snippet
    # (terminal-injection guard).
    snippet = html_comments(_html(b"<!-- \x1b[31mwe are hiring\x1b[0m -->"))[0].snippet
    assert "\x1b" not in snippet
    assert "hiring" in snippet


def test_html_comments_caps_scanned_body_length() -> None:
    # DoS guard: content past _MAX_SCAN_BYTES is not scanned, so a comment beyond the
    # cap is never found (and an unclosed-comment flood cannot spin the CPU).
    from polyfetch_scrape.contrib.easter_hunt import detectors

    body = b"x" * detectors._MAX_SCAN_BYTES + b"<!-- we are hiring -->"
    assert html_comments(_html(body)) == []


# --------------------------------------------------------------------------- #
# weird_headers
# --------------------------------------------------------------------------- #


def test_weird_headers_only_boring_returns_empty_list() -> None:
    # Common headers carry no signal: none are in the curated weird table.
    boring = {
        "content-type": "text/html",
        "server": "nginx",
        "date": "Wed, 01 Jan 2026 00:00:00 GMT",
        "cache-control": "no-cache",
        "etag": '"abc123"',
        "vary": "Accept-Encoding",
    }
    assert weird_headers(_with_headers(boring)) == []


def test_weird_headers_unknown_custom_header_produces_no_finding() -> None:
    # Curated-set strategy: an unknown non-boring header is NOT emitted (precision
    # over recall). A wildcard "emit anything unusual" impl would fail this.
    assert weird_headers(_with_headers({"x-acme-internal-trace": "42"})) == []


def test_weird_headers_p3p_is_policy_notable() -> None:
    findings = weird_headers(_with_headers({"p3p": 'CP="This is not a privacy policy"'}))

    assert len(findings) == 1
    f = findings[0]
    assert f.detector == "weird_headers"
    assert f.category == "policy"
    assert f.severity == "notable"
    assert f.location == "header:p3p"
    assert f.confidence == 0.95
    assert f.url == "https://example.com/"
    assert f.snippet.startswith("p3p: CP=")


def test_weird_headers_clacks_overhead_is_novelty() -> None:
    findings = weird_headers(_with_headers({"x-clacks-overhead": "GNU Terry Pratchett"}))
    assert (findings[0].category, findings[0].severity) == ("novelty", "info")


def test_weird_headers_hire_me_is_recruiting() -> None:
    findings = weird_headers(_with_headers({"x-hire-me": "careers@acme.test"}))
    assert (findings[0].category, findings[0].severity) == ("recruiting", "notable")


def test_weird_headers_powered_by_is_stack_disclosure() -> None:
    findings = weird_headers(_with_headers({"x-powered-by": "PHP/8.2.0"}))
    assert (findings[0].category, findings[0].severity) == ("stack", "info")


def test_weird_headers_request_id_is_low_confidence_stack() -> None:
    # Distinct 0.6 confidence row: a typo dropping it to the default would be caught.
    findings = weird_headers(_with_headers({"x-request-id": "9f8c-..."}))
    assert findings[0].category == "stack"
    assert findings[0].confidence == 0.6


def test_weird_headers_debug_token_is_exposure_warn() -> None:
    findings = weird_headers(_with_headers({"x-debug-token": "a1b2c3"}))
    assert (findings[0].category, findings[0].severity) == ("exposure", "warn")


def test_weird_headers_multiple_weird_headers_each_emit() -> None:
    headers = {"x-debug-token": "a1b2c3", "x-debug-token-link": "/_profiler/a1b2c3"}
    findings = weird_headers(_with_headers(headers))
    assert len(findings) == 2
    assert all(f.category == "exposure" for f in findings)


def test_weird_headers_mixed_boring_and_weird_returns_only_weird_in_order() -> None:
    headers = {
        "server": "nginx",
        "x-clacks-overhead": "GNU Terry Pratchett",
        "content-type": "text/html",
        "x-hire-me": "yes",
    }
    findings = weird_headers(_with_headers(headers))
    assert [f.location for f in findings] == ["header:x-clacks-overhead", "header:x-hire-me"]


def test_weird_headers_empty_value_still_emits() -> None:
    # Presence of a known-weird header is the signal; an empty value must not
    # suppress it (no `if value:` guard).
    findings = weird_headers(_with_headers({"p3p": ""}))
    assert len(findings) == 1
    assert findings[0].snippet == "p3p: "


def test_weird_headers_snippet_truncated_to_120() -> None:
    findings = weird_headers(_with_headers({"x-powered-by": "v" * 200}))
    assert len(findings[0].snippet) == 120


def test_weird_headers_url_is_taken_from_response() -> None:
    findings = weird_headers(_with_headers({"p3p": "CP=..."}, url="https://acme.test/x"))
    assert findings[0].url == "https://acme.test/x"


# --------------------------------------------------------------------------- #
# wellknown_present
# --------------------------------------------------------------------------- #


def _wk(path: str, *, status: int = 200, body: bytes = b"data") -> Response:
    return Response(
        url=f"https://example.com{path}",
        status=status,
        headers={},
        body=body,
        content_type=None,
        backend="httpx",
    )


def test_wellknown_present_non_200_returns_empty_list() -> None:
    assert wellknown_present(_wk("/security.txt", status=404)) == []


def test_wellknown_present_redirect_status_returns_empty_list() -> None:
    # Gate is `status == 200`, not `status < 400`: a 301 to a login page is not presence.
    assert wellknown_present(_wk("/security.txt", status=301)) == []


def test_wellknown_present_unknown_path_returns_empty_list() -> None:
    assert wellknown_present(_wk("/some/app/route", status=200)) == []


def test_wellknown_present_negative_control_path_returns_empty_list() -> None:
    # /404-not-a-real-page is in WELL_KNOWN_PATHS (a probe) but deliberately absent
    # from the classification table, so even a 200 must yield nothing.
    assert wellknown_present(_wk("/404-not-a-real-page", status=200)) == []


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("/humans.txt", "stack"),
        ("/robots.txt", "policy"),
        ("/ads.txt", "policy"),
        ("/security.txt", "policy"),
        ("/.well-known/security.txt", "policy"),
        ("/.well-known/dnt-policy.txt", "policy"),
        ("/.well-known/change-password", "policy"),
        ("/.well-known/gpc.json", "policy"),
        ("/sitemap.xml", "stack"),
        ("/manifest.json", "stack"),
    ],
)
def test_wellknown_present_presence_paths_classify(path: str, category: str) -> None:
    # One assertion per table row: a typo in any non-exposure row is caught here.
    findings = wellknown_present(_wk(path))

    assert len(findings) == 1
    f = findings[0]
    assert f.detector == "wellknown_present"
    assert f.category == category
    assert f.severity == "info"
    assert f.confidence == 1.0
    assert f.location == f"path:{path}"
    assert f.url == f"https://example.com{path}"


def test_wellknown_present_git_head_ref_is_exposure_warn() -> None:
    findings = wellknown_present(_wk("/.git/HEAD", body=b"ref: refs/heads/main\n"))

    assert len(findings) == 1
    f = findings[0]
    assert f.category == "exposure"
    assert f.severity == "warn"
    assert f.confidence == 0.9
    assert f.location == "path:/.git/HEAD"


def test_wellknown_present_git_head_detached_sha_is_exposure() -> None:
    # Detached HEAD: a bare 40-hex sha must also pass the sniff.
    findings = wellknown_present(_wk("/.git/HEAD", body=b"a" * 40 + b"\n"))
    assert findings[0].category == "exposure"


def test_wellknown_present_git_head_html_soft404_is_not_exposure() -> None:
    # Many sites serve a 200 SPA shell for every path; the sniff gate must reject
    # HTML so we never raise a false exposure alarm. Highest-value guard here.
    body = b"<!DOCTYPE html><html><body>Not found</body></html>"
    assert wellknown_present(_wk("/.git/HEAD", body=body)) == []


def test_wellknown_present_dotenv_with_keyvalue_is_exposure_warn() -> None:
    findings = wellknown_present(_wk("/.env", body=b"DATABASE_URL=postgres://u:p@h/db\n"))
    assert (findings[0].category, findings[0].severity) == ("exposure", "warn")


def test_wellknown_present_dotenv_html_soft404_is_not_exposure() -> None:
    assert wellknown_present(_wk("/.env", body=b"<html><body>home</body></html>")) == []


def test_wellknown_present_dotenv_json_error_body_is_not_exposure() -> None:
    # A JSON 200 error page must not match the KEY=val sniff.
    assert wellknown_present(_wk("/.env", body=b'{"error": "not found"}')) == []


def test_wellknown_present_snippet_truncated_to_120() -> None:
    findings = wellknown_present(_wk("/robots.txt", body=b"User-agent: *\n" + b"#" * 200))
    assert len(findings[0].snippet) <= 120
