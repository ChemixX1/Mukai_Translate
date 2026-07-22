"""Public configuration for Mukai's distribution channel.

These values are deliberately kept separate from the updater implementation so a
release is never accidentally pointed at the upstream Comic Translate project.
Before producing the customer installer, set them to the public WordPress
endpoint and the RSA public key shown in the Mukai Licenses page.

Only public values belong here.  Never put a WordPress password, private key,
or hosting credential in the desktop application.
"""

# Public REST namespace used for first-run activation and validation.
LICENSE_API_BASE = "https://mangamukai.com/wp-json/mukai-license/v1"

UPDATE_MANIFEST_URL = f"{LICENSE_API_BASE}/update"

# Base64-encoded 3072-bit RSA public key produced by the WordPress Mukai plugin.
UPDATE_PUBLIC_KEY = (
    "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0KTUlJQm9qQU5CZ2txaGtpRzl3MEJBUUVGQUFPQ0FZOEFNSUlCaWdLQ0FZRUFyZ05Da3BaaWlIcUE0MkhSc0M2Zg"
    "preEROeW1EYU1xT2RDWHhhTkZWK1RzVXN6WnlqSVNRRmVTZU9ISTdaMWc5d1lVTDVaK2pET3JaRGpyczJ4L2p6Cm1EbUZwTmlmYlNZbzFqKzF3WTFsdHhKNSt0"
    "N1BhQS8xRVN5eFVSbitqekNIelQwNDBtQ3VGUlFRbE9LYUkwUnAKdmt1d1FlMEJYekM5ZmZOcVVhWDFuZUxLVER4L3ZkK1ZaektORXRkQ1BaalJGbGdqYzErV2"
    "9oWDBHNmowVXhTVQp1a2NDRTVlcm0zZHRGYWxhV0tVQW9xU0h4Vk9YMDNkWTBEc3JPQVJSSzVnMzNOdCt0RGNGSjA2OEs3SkV5Nm5aCmV1RHMvVlIyNjhpaFl0"
    "NU9PYzJaWVBmTWJBODhKRGM5UXZJSFJyN3Q5Tk42Wkw1MzdHTk90TkRKVTBOS09heHAKUXBVZmRKQlFCaWZUT1RzZHdZQzJOV2oxNzFFQmZQV3U3bFUrWVE2dnpD"
    "RXpOUURIL25WdUhjZ1UySU13eTA4ZApnY2xHYy9Wa2NISGhVaE9PWWV2MWV2ckJpdW96MHVPZGl5QWRYMHFIa25OQU5KME12RlRRT2lRZkdTdkQrYWgwCjVNV2R"
    "VMm1raTVvQ1FiVTdUbUVHaU9Ib1orOWJoaG1JMGRybDU0NmN5VnhUQWdNQkFBRT0KLS0tLS1FTkQgUFVCTElDIEtFWS0tLS0tCg=="
)
