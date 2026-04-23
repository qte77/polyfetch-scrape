# Roadmap

## 0.1.0 — HTTP Client

`httpx`-based HTTP client with retry logic and typed responses.

**Goals**:

- Async and sync `httpx` client wrapper
- Configurable retry with backoff
- Typed response model (status, headers, body, content-type)

## 0.2.0 — TLS Fallback

`curl_cffi` TLS-fingerprint fallback for sites that block standard TLS stacks.

**Goals**:

- Drop-in fallback when `httpx` receives 403/429 or TLS error
- Browser TLS profile selection (chrome, firefox)
- Unified response type shared with 0.1.0 client

## 0.3.0 — JS-Render Fallback

Playwright fallback for pages requiring JavaScript execution.

**Goals**:

- Triggered automatically when curl_cffi fallback also fails
- Wait-for-selector + full-page HTML extraction
- Shared response type; caller receives same structure regardless of backend

## 0.4.0 — API Wrappers

Domain-specific wrappers for document APIs.

**Goals**:

- arXiv bulk download (OAI-PMH + direct PDF)
- USPTO full-text search and patent PDF retrieval
- EUR-Lex SPARQL/REST queries
- legislation.gov.uk REST API
- WIPO PATENTSCOPE REST API

## 0.5.0 — LLM-Ready Output

Structured Markdown and JSON extraction for downstream LLM consumption.

**Goals**:

- HTML-to-Markdown conversion with metadata preservation
- JSON schema for structured document fields (title, abstract, sections, citations)
- Clean text extraction (strip boilerplate, navigation, ads)
