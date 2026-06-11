"""Well-known paths swept by the opt-in ``--include-wellknown`` mode.

The final entry ``/404-not-a-real-page`` is a deliberate negative control: it
has no row in the ``wellknown_present`` classification table, so a 200 response
for it must still yield no Finding.
"""

WELL_KNOWN_PATHS: tuple[str, ...] = (
    "/humans.txt",
    "/robots.txt",
    "/ads.txt",
    "/security.txt",
    "/.well-known/security.txt",
    "/.well-known/dnt-policy.txt",
    "/.well-known/change-password",
    "/.well-known/gpc.json",
    "/sitemap.xml",
    "/manifest.json",
    "/.git/HEAD",
    "/.env",
    "/404-not-a-real-page",
)
