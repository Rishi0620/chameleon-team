"""Shared platform-size catalogue for the CHAMELEON debate bench (26 real formats, exact px)."""
CATALOGUE: dict[str, tuple[int, int]] = {
    "ig_post": (1080, 1080), "ig_portrait": (1080, 1350), "ig_story": (1080, 1920),
    "ig_landscape": (1080, 566), "fb_post": (1200, 630), "fb_cover": (820, 312),
    "fb_event": (1920, 1005), "x_post": (1600, 900), "x_header": (1500, 500),
    "li_post": (1200, 627), "li_banner": (1584, 396), "pin": (1000, 1500),
    "yt_thumb": (1280, 720), "yt_channel": (2560, 1440), "slide_16x9": (1920, 1080),
    "leaderboard": (728, 90), "large_leaderboard": (970, 90), "billboard": (970, 250),
    "med_rect": (300, 250), "large_rect": (336, 280), "half_page": (300, 600),
    "skyscraper": (160, 600), "mobile_banner": (320, 50), "large_mobile": (320, 100),
    "email_header": (600, 200), "letter_flyer": (1275, 1650),
}


def band(w: int, h: int) -> str:
    """Coarse shape band used to slice the scoreboard."""
    r = w / h
    if r >= 4.0:
        return "strip"        # leaderboards, mobile banners, LinkedIn banner
    if r >= 1.6:
        return "wide"         # 16:9, 1.91:1, 3:1 headers
    if r >= 0.7:
        return "squareish"    # 1:1, 4:5, 6:5, 300x250
    return "tall"             # story, skyscraper, half page, pin


# Representative subset for contact sheets (one or two per band).
SHEET_SIZES = ["ig_post", "ig_story", "skyscraper", "yt_thumb", "li_banner", "leaderboard",
               "mobile_banner", "med_rect"]
