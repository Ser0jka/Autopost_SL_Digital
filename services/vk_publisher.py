import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method"


class VKPublishError(Exception):
    pass


def vk_is_configured() -> bool:
    config = get_config()
    return bool(_vk_access_token() and config.VK_GROUP_ID)


def _vk_access_token() -> str:
    config = get_config()
    return config.VK_USER_ACCESS_TOKEN or config.VK_ACCESS_TOKEN


async def publish_vk_photo_post(image_path: str, caption: str) -> int:
    config = get_config()
    if not _vk_access_token():
        raise VKPublishError("VK_USER_ACCESS_TOKEN or VK_ACCESS_TOKEN is not set")
    if not config.VK_GROUP_ID:
        raise VKPublishError("VK_GROUP_ID is not set")

    group_id = abs(int(config.VK_GROUP_ID))
    owner_id = -group_id

    async with httpx.AsyncClient(timeout=120.0) as client:
        upload_url = await _get_upload_url(client, group_id)
        uploaded = await _upload_photo(client, upload_url, image_path)
        saved_photo = await _save_wall_photo(client, group_id, uploaded)

        photo_owner_id = saved_photo.get("owner_id", owner_id)
        photo_id = saved_photo.get("id")
        if not photo_id:
            raise VKPublishError(f"VK did not return saved photo id: {saved_photo}")

        attachment = f"photo{photo_owner_id}_{photo_id}"
        post_id = await _wall_post(client, owner_id, caption, attachment)
        logger.info("Published VK post %s with attachment %s", post_id, attachment)
        return int(post_id)


async def publish_vk_text_post(caption: str) -> int:
    config = get_config()
    if not _vk_access_token():
        raise VKPublishError("VK_USER_ACCESS_TOKEN or VK_ACCESS_TOKEN is not set")
    if not config.VK_GROUP_ID:
        raise VKPublishError("VK_GROUP_ID is not set")

    owner_id = -abs(int(config.VK_GROUP_ID))
    async with httpx.AsyncClient(timeout=120.0) as client:
        post_id = await _wall_post(client, owner_id, caption, "")
        logger.info("Published VK text post %s", post_id)
        return int(post_id)


async def _vk_method(client: httpx.AsyncClient, method: str, data: dict[str, Any]) -> Any:
    config = get_config()
    payload = {
        **data,
        "access_token": _vk_access_token(),
        "v": config.VK_API_VERSION,
    }
    response = await client.post(f"{VK_API_URL}/{method}", data=payload)
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        error = body["error"]
        message = error.get("error_msg") or str(error)
        code = error.get("error_code")
        if code == 27 and "group auth" in message.lower():
            raise VKPublishError(
                "VK не разрешил загрузку фото по токену сообщества. "
                "Заполни VK_USER_ACCESS_TOKEN пользовательским токеном аккаунта "
                "с правами photos, wall и правами администратора/редактора в сообществе."
            )
        raise VKPublishError(f"VK API {method} error {code}: {message}")
    if "response" not in body:
        raise VKPublishError(f"VK API {method} returned unexpected response: {body}")
    return body["response"]


async def _get_upload_url(client: httpx.AsyncClient, group_id: int) -> str:
    response = await _vk_method(client, "photos.getWallUploadServer", {"group_id": group_id})
    upload_url = response.get("upload_url")
    if not upload_url:
        raise VKPublishError(f"VK did not return upload_url: {response}")
    return str(upload_url)


async def _upload_photo(client: httpx.AsyncClient, upload_url: str, image_path: str) -> dict[str, Any]:
    path = Path(image_path)
    if not path.exists():
        raise VKPublishError(f"Image file does not exist: {image_path}")

    with path.open("rb") as photo_file:
        response = await client.post(upload_url, files={"photo": (path.name, photo_file, "image/png")})
    response.raise_for_status()
    body = response.json()
    for key in ("server", "photo", "hash"):
        if key not in body:
            raise VKPublishError(f"VK upload response missing {key}: {body}")
    return body


async def _save_wall_photo(
    client: httpx.AsyncClient,
    group_id: int,
    uploaded: dict[str, Any],
) -> dict[str, Any]:
    response = await _vk_method(
        client,
        "photos.saveWallPhoto",
        {
            "group_id": group_id,
            "server": uploaded["server"],
            "photo": uploaded["photo"],
            "hash": uploaded["hash"],
        },
    )
    if not response:
        raise VKPublishError("VK did not return saved photo")
    if not isinstance(response, list):
        raise VKPublishError(f"VK saveWallPhoto returned unexpected response: {response}")
    return response[0]


async def _wall_post(
    client: httpx.AsyncClient,
    owner_id: int,
    caption: str,
    attachment: str,
) -> int:
    data = {
        "owner_id": owner_id,
        "from_group": 1,
        "message": caption,
    }
    if attachment:
        data["attachments"] = attachment
    response = await _vk_method(client, "wall.post", data)
    post_id = response.get("post_id")
    if not post_id:
        raise VKPublishError(f"VK did not return post_id: {response}")
    return int(post_id)
