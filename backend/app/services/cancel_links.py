"""Where to go to cancel a subscription yourself.

Nothing here contacts a merchant: the bank feed is read-only, and this app cannot
cancel anything. It only knows, for common subscriptions, which page the merchant's
own cancel button lives on — and that a charge billed through Apple, Google Play,
Amazon, Roku or PayPal has to be cancelled with that platform, not the merchant.

ponytail: a hand-kept dict, not a table or a fetched directory. Every address was
checked to resolve on 2026-10-13; they will drift. A user-pasted cancel_url always
wins over these, so a stale entry costs one wrong click, not a dead end. Move this to
data only if households need to add their own shared entries.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CancelHelp:
    url: str
    via: str | None = None  # the billing platform, when the charge is not direct
    steps: str | None = None


@dataclass(frozen=True)
class _Platform:
    name: str
    markers: tuple[str, ...]  # matched against the lower-cased raw label
    url: str
    steps: str


PLATFORMS: tuple[_Platform, ...] = (
    _Platform(
        "Apple",
        ("apple.com/bill", "itunes"),
        "https://apps.apple.com/account/subscriptions",
        "Billed through your Apple account. On an iPhone: Settings, your name, "
        "Subscriptions. Cancelling in the app itself will not stop the charge.",
    ),
    _Platform(
        "Google Play",
        ("google *", "google*", "google play"),
        "https://play.google.com/store/account/subscriptions",
        "Billed through Google Play. Open the link signed in to the Google account "
        "that pays, pick the subscription, and choose Cancel.",
    ),
    _Platform(
        "Amazon",
        ("amzn digital", "amazon digital", "prime video channels", "amazon channels"),
        "https://www.amazon.com/yourmembershipsandsubscriptions",
        "Billed through your Amazon account. Open Memberships & Subscriptions, find "
        "it in the list, and choose Cancel subscription.",
    ),
    _Platform(
        "Roku",
        ("roku",),
        "https://my.roku.com/account/subscriptions",
        "Billed through your Roku account. Sign in, open Manage your subscriptions, "
        "and unsubscribe there.",
    ),
    _Platform(
        "PayPal",
        ("paypal", "pp*"),
        "https://www.paypal.com/myaccount/autopay/",
        "Paid by a PayPal automatic payment. Cancelling it here stops the money; "
        "also cancel with the merchant so the account itself is closed.",
    ),
)

# Key: the merchant's name as lower-case words. Matched on word boundaries against
# the label with punctuation flattened, so "netflix" finds "NETFLIX.COM #4471" and
# "max" does not find "Maxwell Hardware".
MERCHANT_LINKS: dict[str, str] = {
    "netflix": "https://www.netflix.com/cancelplan",
    "hulu": "https://secure.hulu.com/account",
    "disney plus": "https://www.disneyplus.com/commerce/subscription",
    "disneyplus": "https://www.disneyplus.com/commerce/subscription",
    "hbo max": "https://auth.hbomax.com/account",
    "hbomax": "https://auth.hbomax.com/account",
    "max": "https://auth.hbomax.com/account",
    "spotify": "https://www.spotify.com/account/subscription/",
    "youtube": "https://www.youtube.com/paid_memberships",
    "amazon prime": "https://www.amazon.com/gp/primecentral",
    "kindle unlimited": "https://www.amazon.com/kindle-dbs/ku/ku-central",
    "peacock": "https://www.peacocktv.com/account/plans",
    "audible": "https://www.audible.com/account/overview",
    "adobe": "https://account.adobe.com/plans",
    "dropbox": "https://www.dropbox.com/account/plan",
    "microsoft": "https://account.microsoft.com/services",
    "xbox": "https://account.microsoft.com/services",
    "new york times": "https://www.nytimes.com/account/subscription",
    "nytimes": "https://www.nytimes.com/account/subscription",
    "wall street journal": "https://customercenter.wsj.com/public",
    "wsj": "https://customercenter.wsj.com/public",
    "linkedin": "https://www.linkedin.com/premium/manage/",
    "duolingo": "https://www.duolingo.com/settings/super",
    "claude": "https://claude.ai/settings/billing",
    "anthropic": "https://claude.ai/settings/billing",
    "canva": "https://www.canva.com/settings/billing-and-plans",
    "zoom": "https://zoom.us/billing",
    "headspace": "https://my.headspace.com/profile/subscription/manage",
    "crunchyroll": "https://www.crunchyroll.com/account/membership",
    "siriusxm": "https://care.siriusxm.com/",
    "sirius xm": "https://care.siriusxm.com/",
    "instacart": "https://www.instacart.com/store/account/instacart-plus",
    "nordvpn": "https://my.nordaccount.com/billing/my-subscriptions/",
    "grammarly": "https://account.grammarly.com/subscription",
    "sling": "https://www.sling.com/account",
    "discovery plus": "https://auth.discoveryplus.com/my-account",
    "discoveryplus": "https://auth.discoveryplus.com/my-account",
    "strava": "https://www.strava.com/settings/account",
    "patreon": "https://www.patreon.com/settings/memberships",
    "twitch": "https://www.twitch.tv/subscriptions",
    "fubo": "https://www.fubo.tv/account/subscription",
}

# Longest name first, so "amazon prime" is tried before a shorter name could claim it.
_MERCHANT_PATTERNS = [
    (re.compile(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])"), url)
    for name, url in sorted(MERCHANT_LINKS.items(), key=lambda kv: -len(kv[0]))
]


def lookup(label: str) -> CancelHelp | None:
    """Cancellation help for a series label, or None when nothing is known.

    A platform marker wins over a merchant name: "PAYPAL *SPOTIFY" is cancelled at
    PayPal, whatever Spotify's own page says.
    """
    raw = (label or "").lower()
    for p in PLATFORMS:
        if any(m in raw for m in p.markers):
            return CancelHelp(url=p.url, via=p.name, steps=p.steps)
    flat = re.sub(r"[^a-z0-9]+", " ", raw.replace("+", " plus "))
    for pattern, url in _MERCHANT_PATTERNS:
        if pattern.search(flat):
            return CancelHelp(url=url)
    return None
