### Fixed

- Patchright tier: reading the page while a client-side redirect is in flight (e.g. `--wait-until domcontentloaded` on a page that then redirects to a login wall) no longer crashes with Patchright's raw `Page.content: Unable to retrieve content because the page is navigating` traceback. The backend now waits for the new document's load state and reads the settled page; if it is still navigating, it raises a `FetchError` that names the cause and suggests `--wait-until networkidle` (#256).
