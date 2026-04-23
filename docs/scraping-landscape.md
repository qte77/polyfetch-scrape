---
title: Web Scraping and Data Extraction — Tool Landscape
description: Survey of scraping, crawling, and extraction tools (2025-2026)
created: 2026-04-23
updated: 2026-04-23
urls_validated: 2026-04-23
---

Survey of available tools for HTTP requests, browser automation, AI-native scraping, search APIs, managed platforms, document extraction, and anti-bot bypass. Focused on what's actively maintained and relevant as of 2025-2026.

## Claude Code Built-in Web Tools

Claude Code provides two built-in tools for web access — no setup required.

| Tool | What it does | Limitations |
|------|-------------|-------------|
| **WebSearch** | Search query → titles + URLs (Claude.ai backend) | US-only; returns URLs only, not content |
| **WebFetch** | URL → HTML-to-markdown → LLM summary | No JS rendering; 10MB limit; PDF bug (returns binary); 15-min cache |
| **Read** | Local PDF/image parsing (poppler-utils) | Max 20 pages/request; not a web tool |

**Key gaps**: no JS rendering, no browser state/auth, no batch ops, no anti-bot bypass, PDF fetching broken in CC wrapper (works in API). For anything beyond simple URL fetching, use an external tool below.

See [CC Web Scraping Plugins Analysis](https://github.com/qte77/ai-agents-research/blob/main/docs/cc-native/plugins-ecosystem/CC-web-scraping-plugins-analysis.md) for detailed comparison of CC built-in vs Firecrawl MCP vs Playwright MCP.

## HTTP Clients

| Tool | License | TLS Fingerprinting | Differentiator |
|------|---------|-------------------|----------------|
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | MIT | Yes (JA3/HTTP2/HTTP3) | Impersonates Chrome 99-146; fastest TLS bypass |
| [tls_client](https://github.com/FlorianREGAZ/Python-Tls-Client) | MIT | Yes (JA3) | Go-based, simpler API, Python bindings |
| [httpx](https://github.com/encode/httpx) | BSD-3 | No | Modern async/sync client, HTTP/2; no anti-bot |
| [aiohttp](https://github.com/aio-libs/aiohttp) | Apache-2.0 | No | High-performance async; no TLS spoofing |

**When to use what**: curl_cffi for sites with TLS fingerprinting. httpx for everything else.

## Browser Automation

| Tool | License | Anti-Detection | Differentiator |
|------|---------|---------------|----------------|
| [Playwright](https://playwright.dev/) | Apache-2.0 | None built-in | Fast, modern API, multi-browser |
| [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) | Apache-2.0 | CDP leak patches | Undetected Playwright fork; Chromium only |
| [SeleniumBase](https://seleniumbase.io/) (UC Mode) | MIT | Cloudflare, CAPTCHAs | Auto CAPTCHA solving; Playwright bridge |
| [Nodriver](https://github.com/ultrafunkamsterdam/nodriver) | MIT | General anti-bot | No driver binary; avoids detection vectors entirely |
| [Botasaurus](https://github.com/omkarcloud/botasaurus) | MIT | Cloudflare, DataDome | Passes nowsecure.nl + g2.com benchmarks |
| [Camoufox](https://camoufox.com/) | MPL-2.0 | Engine-level fingerprint | Modified Firefox build; C++-level patching; experimental |

**When to use what**: Playwright for JS rendering without anti-bot. Patchright or Nodriver when detection is an issue. Botasaurus for the hardest targets.

## Scraping Frameworks

| Tool | License | Language | Differentiator |
|------|---------|----------|----------------|
| [Scrapy](https://scrapy.org/) | BSD-3 | Python | Battle-tested at scale; huge plugin ecosystem |
| [Crawlee](https://crawlee.dev/) | Apache-2.0 | JS/TS + Python | Unified HTTP + browser crawling; Apify integration |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | MIT | Python | Adaptive selectors survive site redesigns; MCP server |
| [ScrapFly](https://scrapfly.io/) | SaaS | API | Managed anti-bot bypass; from $30/mo |
| [ZenRows](https://www.zenrows.com/) | SaaS | API | JS rendering + premium proxies; from $69/mo |

## AI/LLM-Native Scrapers

| Tool | License | Pricing | Differentiator |
|------|---------|---------|----------------|
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | Apache-2.0 | Free | Fully local, no API keys, Markdown/JSON output |
| [Firecrawl](https://www.firecrawl.dev/) | AGPL-3.0 | Free–$333/mo | One API call = clean Markdown; self-hostable |
| [ScrapeGraphAI](https://scrapegraphai.com/) | MIT | Free–$500/mo | Natural language prompts build scraping pipelines |
| [Jina Reader](https://jina.ai/reader/) | Apache-2.0 | 50K free/mo | HTML→Markdown via SLM (ReaderLM-v2) |
| [Diffbot](https://www.diffbot.com/) | SaaS | From $299/mo | CV-based auto-extraction; Knowledge Graph API |

**When to use what**: Crawl4AI for free local LLM-ready output. Firecrawl for managed/enterprise. Jina for lightweight HTML→Markdown.

## Search APIs

| Tool | Free Tier | Pricing | Differentiator |
|------|-----------|---------|----------------|
| [Exa](https://exa.ai/) | 2K one-time | ~$5/1K queries | Neural/semantic search; 81% retrieval accuracy |
| [Tavily](https://tavily.com/) | 1K/mo | Credit-based | 93% SimpleQA accuracy; acquired by Nebius |
| [Serper](https://serper.dev/) | 2.5K | ~$50/mo | Google SERP proxy with knowledge graphs |
| [SerpAPI](https://serpapi.com/) | Limited | $10-25/1K | Multi-engine (Google, Bing, Baidu, Yandex) |
| [Brave Search](https://brave.com/search/api/) | 2K/mo | From $5/mo | Independent index (35B+ pages); privacy-focused |

**When to use what**: Exa for semantic/RAG retrieval. Tavily for factual accuracy. Brave for privacy-conscious search.

## Managed Scraping Platforms

| Platform | Entry Price | Self-Hostable | Differentiator |
|----------|-------------|---------------|----------------|
| [Apify](https://apify.com/) | Free; $29/mo | No | 20K+ ready-made Actors; full pipeline platform |
| [Browserbase](https://www.browserbase.com/) | ~$50/mo | No | Hosted browser infra for AI agents |
| [Steel](https://steel.dev/) | Free; $29/mo | Yes (Docker) | OSS browser API; sub-second sessions; MCP integration |
| [ScrapingBee](https://www.scrapingbee.com/) | $49/mo | No | Simple API; 84% success rate |
| [Bright Data](https://brightdata.com/) | $1.50/1K req | No | 98.4% success rate; largest proxy network |
| [Oxylabs](https://oxylabs.io/) | $49/mo | No | 98.1% success rate; Web Scraper AI product |

## Document-Specific Extraction

| Tool | Target | License | Notes |
|------|--------|---------|-------|
| [legislation.gov.uk API](https://www.legislation.gov.uk/developer) | UK legislation | Free | Official REST API; XML/HTML; bypasses PDF download issues |
| [Lex API](https://lex.lab.i.ai.gov.uk/) | UK legislation | Free | AI-oriented API with semantic search + MCP server |
| [eurlex (R)](https://michalovadek.github.io/eurlex/) | EUR-Lex | MIT | SPARQL + REST wrapper; bulk download all EU languages |
| [scrapelex (Python)](https://github.com/bocchilorenzo/scrapelex) | EUR-Lex | OSS | BeautifulSoup-based bulk downloader |
| [paperscraper](https://github.com/jannisborn/paperscraper) | arXiv, PubMed | Apache-2.0 | Full-text download via DOI |
| [arXiv Bulk Access](https://info.arxiv.org/help/bulk_data.html) | arXiv | Free | Official S3/GCS bulk access to source + metadata |
| [USPTO Open Data](https://developer.uspto.gov/) | US patents | Free | Bulk data, PatentsView API, full-text search |
| [EPO Open Patent Services](https://www.epo.org/en/searching-for-patents/data/web-services/ops) | EU patents | Free (fair use) | REST API; bibliographic, legal, full-text data |
| [Google Patents Public Datasets](https://cloud.google.com/blog/topics/public-datasets/google-patents-public-datasets-connecting-public-paid-and-private-patent-data) | Global patents | Free (BigQuery) | 120M+ patents; full text, claims, citations |
| [Lens.org API](https://www.lens.org/) | Patents + scholarly | Free (academic) | Unified patent + scholarly search; bulk export |
| [WIPO PATENTSCOPE](https://patentscope.wipo.int/search/en/structuredSearch.jsf) | PCT patents | Free | International patent search; bulk XML download |

**Key insight**: government legislation portals and patent offices have official APIs that are easier than fighting their anti-bot. Use the API, not the PDF download page.

## Browser-as-a-Service / Agent Platforms

| Platform | License/Pricing | Differentiator |
|----------|----------------|----------------|
| [Steel](https://steel.dev/) | MIT (core); cloud from $29/mo | Sub-second sessions, 24h persistence, anti-bot + CAPTCHA |
| [Hyperbrowser](https://www.hyperbrowser.ai/) | HyperAgent OSS; cloud from $99/mo | Three-tier API (ai/perform/extract), 10K+ concurrent browsers |
| [TinyFish](https://www.tinyfish.ai/) | SaaS from $15/mo | Unified search + fetch + browser + agent under one API key |
| GoWatch | SaaS (YC W25) | AI agent-based web monitoring; pivoting — site down as of 2026-04 |

## Research and Monitoring Products

| Product | Pricing | Differentiator |
|---------|---------|----------------|
| [Exa Websets](https://exa.ai/websets) | From $49/mo | AI agents search 20K+ sources, verify and structure results |
| [Firecrawl Open Scouts](https://github.com/firecrawl/open-scouts) | OSS (self-host) | Scheduled web monitoring with email alerts; uses Firecrawl API |

## Integration: Prefer APIs over MCP

Most tools listed above offer both proper REST/SDK APIs and MCP servers. For production use, prefer the direct API — it's faster, typed, versioned, and doesn't depend on the MCP runtime. MCP is useful for interactive AI agent sessions but adds a layer of indirection.

| Tool | API | MCP available |
|------|-----|---------------|
| [Firecrawl](https://docs.firecrawl.dev/api-reference) | REST + Python/JS SDK | Yes |
| [Exa](https://docs.exa.ai/) | REST + Python/JS SDK | Yes |
| [Steel](https://docs.steel.dev/) | REST + Python/JS SDK | Yes |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | Python library | Yes |
| [Bright Data](https://docs.brightdata.com/) | REST | Yes |
| [Apify](https://docs.apify.com/api) | REST + Python/JS SDK | Yes |
| [Lex API](https://lex.lab.i.ai.gov.uk/) | REST | Yes |

## Anti-Bot Bypass

| Tool | Type | Targets |
|------|------|---------|
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | OSS (MIT) | TLS/JA3 fingerprinting |
| [Nodriver](https://github.com/ultrafunkamsterdam/nodriver) | OSS (MIT) | Cloudflare, general anti-bot |
| [SeleniumBase UC Mode](https://seleniumbase.io/help_docs/uc_mode/) | OSS (MIT) | Cloudflare, CAPTCHAs |
| [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) | OSS (Apache-2.0) | CDP detection, Cloudflare |
| [Botasaurus](https://github.com/omkarcloud/botasaurus) | OSS (MIT) | Cloudflare, DataDome |
| [ScrapFly](https://scrapfly.io/) | SaaS | Cloudflare, DataDome, Akamai; from $30/mo |

**Reality check**: open-source anti-bot bypasses have a shelf life of months before detection vendors patch them. Commercial APIs invest continuously but cost $1K-5K/mo at scale.

## Decision Flowchart

```text
Need to download a known URL?
  ├─ No anti-bot? → httpx
  ├─ TLS fingerprinting? → curl_cffi
  ├─ Needs JavaScript? → Playwright (or Patchright if detected)
  ├─ Government legislation? → Use the official API
  └─ All else fails? → Managed platform (Bright Data, ScrapFly)

Need to find content?
  ├─ Semantic/RAG? → Exa
  ├─ Factual accuracy? → Tavily
  └─ Privacy? → Brave Search API

Need LLM-ready output?
  ├─ Free/local? → Crawl4AI
  ├─ Managed? → Firecrawl
  └─ Lightweight? → Jina Reader
```
