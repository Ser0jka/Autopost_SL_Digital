import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method"
VK_RETRY_ATTEMPTS = 3
VK_UPLOAD_CHAIN_ATTEMPTS = 2
VK_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
VK_RETRY_API_ERROR_CODES = {6, 9, 10}


class VKPublishError(Exception):
    pass


class VKRetryableError(VKPublishError):
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
        saved_photo = await _upload_and_save_wall_photo(client, group_id, image_path)

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
    last_error: Exception | None = None

    for attempt in range(1, VK_RETRY_ATTEMPTS + 1):
        try:
            response = await client.post(f"{VK_API_URL}/{method}", data=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
            last_error = exc
            if not _is_retryable_http_error(exc) or attempt >= VK_RETRY_ATTEMPTS:
                error_type = VKRetryableError if _is_retryable_http_error(exc) else VKPublishError
                raise error_type(f"VK API {method} request failed: {exc}") from exc
            await _sleep_before_retry(f"VK API {method}", attempt, VK_RETRY_ATTEMPTS, exc)
            continue

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
            if code in VK_RETRY_API_ERROR_CODES and attempt < VK_RETRY_ATTEMPTS:
                await _sleep_before_retry(f"VK API {method} error {code}", attempt, VK_RETRY_ATTEMPTS, message)
                continue
            if code in VK_RETRY_API_ERROR_CODES:
                raise VKRetryableError(f"VK API {method} error {code}: {message}")
            raise VKPublishError(f"VK API {method} error {code}: {message}")

        if "response" not in body:
            last_error = VKPublishError(f"VK API {method} returned unexpected response: {body}")
            if attempt < VK_RETRY_ATTEMPTS:
                await _sleep_before_retry(
                    f"VK API {method} unexpected response",
                    attempt,
                    VK_RETRY_ATTEMPTS,
                    body,
                )
                continue
            raise VKRetryableError(str(last_error)) from last_error

        return body["response"]

    raise VKRetryableError(f"VK API {method} failed after retries: {last_error}")


def _is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in VK_RETRY_STATUS_CODES
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError, ValueError))


async def _sleep_before_retry(operation: str, attempt: int, total_attempts: int, reason: object) -> None:
    delay = min(2 ** attempt, 10)
    logger.warning(
        "%s failed, retrying in %ss (attempt %s/%s): %s",
        operation,
        delay,
        attempt + 1,
        total_attempts,
        reason,
    )
    await asyncio.sleep(delay)


async def _get_upload_url(client: httpx.AsyncClient, group_id: int) -> str:
    response = await _vk_method(client, "photos.getWallUploadServer", {"group_id": group_id})
    upload_url = response.get("upload_url")
    if not upload_url:
        raise VKPublishError(f"VK did not return upload_url: {response}")
    return str(upload_url)


async def _upload_and_save_wall_photo(
    client: httpx.AsyncClient,
    group_id: int,
    image_path: str,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, VK_UPLOAD_CHAIN_ATTEMPTS + 1):
        try:
            upload_url = await _get_upload_url(client, group_id)
            uploaded = await _upload_photo(client, upload_url, image_path)
            return await _save_wall_photo(client, group_id, uploaded)
        except VKRetryableError as exc:
            last_error = exc
            if attempt >= VK_UPLOAD_CHAIN_ATTEMPTS:
                raise
            await _sleep_before_retry("VK upload/save photo chain", attempt, VK_UPLOAD_CHAIN_ATTEMPTS, exc)

    raise VKPublishError(f"VK upload/save photo chain failed after retries: {last_error}")


async def _upload_photo(client: httpx.AsyncClient, upload_url: str, image_path: str) -> dict[str, Any]:
    path = Path(image_path)
    if not path.exists():
        raise VKPublishError(f"Image file does not exist: {image_path}")

    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    last_error: Exception | None = None
    for attempt in range(1, VK_RETRY_ATTEMPTS + 1):
        try:
            with path.open("rb") as photo_file:
                response = await client.post(upload_url, files={"photo": (path.name, photo_file, content_type)})
            response.raise_for_status()
            body = response.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
            last_error = exc
            if not _is_retryable_http_error(exc) or attempt >= VK_RETRY_ATTEMPTS:
                error_type = VKRetryableError if _is_retryable_http_error(exc) else VKPublishError
                raise error_type(f"VK photo upload failed: {exc}") from exc
            await _sleep_before_retry("VK photo upload", attempt, VK_RETRY_ATTEMPTS, exc)
            continue

        missing_keys = [key for key in ("server", "photo", "hash") if key not in body]
        if missing_keys:
            last_error = VKPublishError(f"VK upload response missing {missing_keys}: {body}")
            if attempt < VK_RETRY_ATTEMPTS:
                await _sleep_before_retry(
                    "VK photo upload unexpected response",
                    attempt,
                    VK_RETRY_ATTEMPTS,
                    body,
                )
                continue
            raise VKRetryableError(str(last_error)) from last_error

        return body

    raise VKRetryableError(f"VK photo upload failed after retries: {last_error}")


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
    data["guid"] = str(uuid4())
    response = await _vk_method(client, "wall.post", data)
    post_id = response.get("post_id")
    if not post_id:
        raise VKPublishError(f"VK did not return post_id: {response}")
    return int(post_id)
