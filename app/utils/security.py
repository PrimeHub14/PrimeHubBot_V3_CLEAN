from app.config import settings


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids_set
