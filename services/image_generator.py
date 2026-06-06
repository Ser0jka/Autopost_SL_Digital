import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGE_DIR = BASE_DIR / "data" / "images"


class ImageGenerationError(Exception):
    pass


@dataclass
class ImageResult:
    path: str
    provider: str


class ImageGenerator:
    def __init__(self, config):
        self.config = config
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    async def generate_image(self, prompt: str, post_id: str) -> ImageResult:
        providers = [
            ("huggingface_flux_schnell", self._generate_huggingface),
            ("stability_ai", self._generate_stability),
            ("modelslab", self._generate_modelslab),
            ("fal_ai", self._generate_fal),
        ]
        errors: list[str] = []

        for provider, handler in providers:
            try:
                logger.info("Trying image provider for %s: %s", post_id, provider)
                image_bytes = await handler(prompt)
                if not image_bytes:
                    raise ImageGenerationError("empty image response")
                path = IMAGE_DIR / f"{post_id}.png"
                path.write_bytes(image_bytes)
                logger.info("Generated image for %s via %s", post_id, provider)
                return ImageResult(path=str(path), provider=provider)
            except ImageGenerationError as exc:
                errors.append(f"{provider}: {exc}")
                logger.warning("Image provider failed: %s: %s", provider, exc)
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                logger.exception("Unexpected image provider error: %s", provider)

        detail = "; ".join(errors) if errors else "no configured image providers"
        logger.error("All image providers failed for %s: %s", post_id, detail)
        raise ImageGenerationError(detail)

    async def _generate_huggingface(self, prompt: str) -> bytes:
        if not self.config.HF_API_KEY:
            raise ImageGenerationError("HF_API_KEY not set")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"https://api-inference.huggingface.co/models/{self.config.HF_MODEL}",
                headers={
                    "Authorization": f"Bearer {self.config.HF_API_KEY}",
                    "Accept": "image/*",
                },
                json={
                    "inputs": prompt,
                    "parameters": {
                        "num_inference_steps": 4,
                        "guidance_scale": 0,
                    },
                },
            )
        return self._image_or_error(response)

    async def _generate_stability(self, prompt: str) -> bytes:
        if not self.config.STABILITY_API_KEY:
            raise ImageGenerationError("STABILITY_API_KEY not set")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.stability.ai/v2beta/stable-image/generate/core",
                headers={
                    "Authorization": f"Bearer {self.config.STABILITY_API_KEY}",
                    "Accept": "image/*",
                },
                files={
                    "prompt": (None, prompt),
                    "output_format": (None, "png"),
                    "aspect_ratio": (None, "1:1"),
                },
            )
        return self._image_or_error(response)

    async def _generate_modelslab(self, prompt: str) -> bytes:
        if not self.config.MODELSLAB_API_KEY:
            raise ImageGenerationError("MODELSLAB_API_KEY not set")

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                "https://modelslab.com/api/v6/realtime/text2img",
                json={
                    "key": self.config.MODELSLAB_API_KEY,
                    "prompt": prompt,
                    "width": "1024",
                    "height": "1024",
                    "samples": "1",
                    "safety_checker": True,
                    "enhance_prompt": True,
                    "base64": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            return await self._extract_modelslab_image(client, data)

    async def _generate_fal(self, prompt: str) -> bytes:
        if not self.config.FAL_API_KEY:
            raise ImageGenerationError("FAL_API_KEY not set")

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                "https://fal.run/fal-ai/flux/schnell",
                headers={
                    "Authorization": f"Key {self.config.FAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": prompt,
                    "image_size": "square_hd",
                    "num_inference_steps": 4,
                    "num_images": 1,
                    "enable_safety_checker": True,
                },
            )
            response.raise_for_status()
            data = response.json()
            url = self._first_url(data)
            if not url:
                raise ImageGenerationError(f"no image url in Fal.ai response: {data}")
            return await self._download(client, url)

    def _image_or_error(self, response: httpx.Response) -> bytes:
        content_type = response.headers.get("content-type", "")
        if response.is_success and content_type.startswith("image/"):
            return response.content

        try:
            detail: Any = response.json()
        except ValueError:
            detail = response.text[:500]
        raise ImageGenerationError(f"HTTP {response.status_code}: {detail}")

    async def _extract_modelslab_image(self, client: httpx.AsyncClient, data: dict) -> bytes:
        if data.get("status") not in {"success", "processing"}:
            raise ImageGenerationError(str(data))

        output = data.get("output") or data.get("future_links") or []
        if isinstance(output, str):
            output = [output]
        if output:
            item = output[0]
            if isinstance(item, str) and item.startswith("http"):
                return await self._download(client, item)
            if isinstance(item, str):
                return base64.b64decode(item)

        encoded = data.get("image") or data.get("base64")
        if encoded:
            return base64.b64decode(encoded)

        raise ImageGenerationError(f"no image in ModelsLab response: {data}")

    def _first_url(self, data: dict) -> str:
        images = data.get("images") or []
        if images:
            first = images[0]
            if isinstance(first, dict):
                return first.get("url", "")
            if isinstance(first, str):
                return first
        image = data.get("image")
        if isinstance(image, dict):
            return image.get("url", "")
        if isinstance(image, str):
            return image
        return ""

    async def _download(self, client: httpx.AsyncClient, url: str) -> bytes:
        response = await client.get(url)
        response.raise_for_status()
        if not response.content:
            raise ImageGenerationError(f"empty download: {url}")
        return response.content
