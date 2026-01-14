import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import aiohttp

# Configure logging
logger = logging.getLogger(__name__)


class HTTPClient:
    """
    Async HTTP client wrapper with comprehensive error handling
    """

    def __init__(
        self,
        base_url: str = "",
        default_headers: Dict[str, str] = None,
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_retry_delay: float = 10.0,
        slow_response_threshold: float = 5000,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.default_timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_retry_delay = max_retry_delay
        self.slow_response_threshold = slow_response_threshold / 1000  # Convert to seconds

    def get_headers(self, additional_headers: Dict[str, str] = None) -> Dict[str, str]:
        """Get headers with optional additional headers"""
        headers = self.default_headers.copy()
        if additional_headers:
            headers.update(additional_headers)
        return headers

    async def _make_request(
            self,
            method: str,
            endpoint: str,
            headers: Dict[str, str] = None,
            params: Dict[str, Any] = None,
            json_data: Dict[str, Any] = None,
            data: Dict[str, Any] = None,
            max_retries: int = 3,
            **kwargs,
    ) -> Tuple[Optional[Any], Optional[str]]:
        """
        Core method to make HTTP requests with retry logic
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if self.base_url else endpoint

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.request(
                            method=method.upper(),
                            url=url,
                            headers=self.get_headers(headers),
                            params=params,
                            json=json_data,
                            data=data,
                            **kwargs,
                    ) as response:

                        # Handle successful response
                        if 200 <= response.status < 300:
                            try:
                                content_type = response.headers.get("content-type", "")
                                if "application/json" in content_type:
                                    data_result = await response.json()
                                else:
                                    data_result = await response.text()

                                return data_result, None

                            except (aiohttp.ContentTypeError, ValueError) as e:
                                error_msg = f"Failed to parse response: {str(e)}"
                                return None, error_msg

                        # Handle HTTP errors (don't retry)
                        else:
                            try:
                                error_text = await response.text()
                                error_msg = f"HTTP {response.status} - {response.reason}"
                                if error_text:
                                    error_msg += f" - {error_text[:200]}"
                            except Exception as ex:
                                error_msg = f"HTTP {response.status} - {response.reason} - {str(ex)}"

                            return None, error_msg

            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < max_retries:
                    # Simple exponential backoff
                    delay = min(2 ** attempt, 10)
                    await asyncio.sleep(delay)
                    continue
                else:
                    return None, f"Request timeout after {max_retries + 1} attempts"

            except aiohttp.ClientError as e:
                # Don't retry other client errors
                return None, f"Network error: {str(e)}"

            except Exception as e:
                return None, f"Unexpected error: {str(e)}"

        return None, f"Failed after {max_retries + 1} attempts"

    async def _make_request_with_timeout_retry(
            self,
            method: str,
            endpoint: str,
            headers: Dict[str, str] = None,
            params: Dict[str, Any] = None,
            json_data: Dict[str, Any] = None,
            data: Dict[str, Any] = None,
            timeout: float = 200, # milliseconds
            max_retries: int = None,
            pause: float = 0.1,
            **kwargs,
    ) -> Tuple[Optional[Any], Optional[str]]:
        """
        Make HTTP request with retry for slow responses (not just timeouts)
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if self.base_url else endpoint

        retries = max_retries if max_retries is not None else self.max_retries
        request_timeout = timeout / 1000

        last_error = None

        for attempt in range(retries + 1):
            start_time = time.time()

            try:
                # Create a timeout for the entire request
                timeout_obj = aiohttp.ClientTimeout(total=request_timeout)

                async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                    # Start timing the actual request
                    request_start = time.time()

                    async with session.request(
                            method=method.upper(),
                            url=url,
                            headers=self.get_headers(headers),
                            params=params,
                            json=json_data,
                            data=data,
                            **kwargs,
                    ) as response:

                        # Check if response was too slow (even if successful)
                        response_time = time.time() - request_start

                        # Log the response time
                        logger.debug(
                            f"Attempt {attempt + 1}/{retries + 1} - "
                            f"HTTP {method.upper()} {url} - "
                            f"Response time: {response_time:.3f}s"
                        )

                        # Handle successful response
                        if 200 <= response.status < 300:
                            try:
                                content_type = response.headers.get("content-type", "")
                                if "application/json" in content_type:
                                    data_result = await response.json()
                                else:
                                    data_result = await response.text()

                                total_time = time.time() - start_time
                                logger.info(
                                    f"Request successful in {total_time:.3f}s "
                                    f"(response: {response_time:.3f}s) - {url}"
                                )

                                return data_result, None

                            except (aiohttp.ContentTypeError, ValueError) as e:
                                error_msg = f"Failed to parse response: {str(e)}"
                                return None, error_msg

                        # Handle HTTP errors (don't retry on HTTP errors)
                        else:
                            try:
                                error_text = await response.text()
                                error_msg = f"HTTP {response.status} - {response.reason}"
                                if error_text:
                                    error_msg += f" - {error_text[:200]}"
                            except Exception as ex:
                                error_msg = f"HTTP {response.status} - {response.reason} - {str(ex)}"

                            logger.warning(f"HTTP error: {error_msg} - URL: {url}")
                            return None, error_msg

            except asyncio.TimeoutError as e:
                last_error = e
                total_time = time.time() - start_time
                logger.warning(
                    f"Timeout after {total_time:.3f}s on attempt {attempt + 1}/{retries + 1} for {url}"
                )

                if attempt < retries:
                    delay = self._calculate_backoff(attempt)
                    await asyncio.sleep(delay)
                    continue
                else:
                    error_msg = f"Request timeout after {retries + 1} attempts"
                    logger.error(f"{error_msg} - URL: {url}")
                    return None, error_msg

            except aiohttp.ClientError as e:
                error_msg = f"Network error: {str(e)}"
                logger.error(f"{error_msg} - URL: {url}")
                return None, error_msg

            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                logger.error(f"{error_msg} - URL: {url}")
                return None, error_msg

            time.sleep(pause)

        return None, f"Failed after {retries + 1} attempts"

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter"""
        delay = min(
            self.retry_delay * (2 ** attempt),
            self.max_retry_delay
        )
        # Add jitter (±20%)
        jitter = delay * 0.2
        delay = delay + (asyncio.get_running_loop().time() % jitter) - (jitter / 2)
        return delay

    # Convenience methods
    async def get(
        self,
        endpoint: str,
        params: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        max_retries: int = 1,
        **kwargs,
    ) -> Tuple[Optional[Any], Optional[str]]:
        return await self._make_request(
            "GET", endpoint, headers=headers, params=params, max_retries=max_retries, **kwargs
        )

    async def get_cut_by_timeout(
            self,
            endpoint: str,
            params: Dict[str, Any] = None,
            headers: Dict[str, str] = None,
            timeout: int = 200, #millisecornds
            max_retries: int = 1,
            **kwargs,
    ) -> Tuple[Optional[Any], Optional[str]]:
        return await self._make_request_with_timeout_retry(
            "GET", endpoint, headers=headers, params=params, max_retries=max_retries, timeout=timeout, **kwargs
        )
    async def post(
        self,
        endpoint: str,
        json_data: Dict[str, Any] = None,
        data: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        **kwargs,
    ) -> Tuple[Optional[Any], Optional[str]]:
        return await self._make_request(
            "POST", endpoint, headers=headers, json_data=json_data, data=data, **kwargs
        )

    async def put(
        self,
        endpoint: str,
        json_data: Dict[str, Any] = None,
        data: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        **kwargs,
    ) -> Tuple[Optional[Any], Optional[str]]:
        return await self._make_request(
            "PUT", endpoint, headers=headers, json_data=json_data, data=data, **kwargs
        )

    async def delete(
        self, endpoint: str, headers: Dict[str, str] = None, **kwargs
    ) -> Tuple[Optional[Any], Optional[str]]:
        return await self._make_request("DELETE", endpoint, headers=headers, **kwargs)
