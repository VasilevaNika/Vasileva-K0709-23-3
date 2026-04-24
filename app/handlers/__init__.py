from app.handlers.main import register_main_router
from app.handlers.registration import register_registration_router
from app.handlers.feed import register_feed_router
from app.handlers.matches import register_matches_router
from app.handlers.profile import register_profile_router

__all__ = [
    "register_main_router",
    "register_registration_router",
    "register_feed_router",
    "register_matches_router",
    "register_profile_router",
]
