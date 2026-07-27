import httpx


async def test_request_hook_restores_sensitive_header_after_cross_origin_redirect() -> None:
    seen: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("Authorization")))
        if request.url.host == "first.test":
            return httpx.Response(307, headers={"location": "https://second.test/mcp"})
        return httpx.Response(200)

    async def restore(request: httpx.Request) -> None:
        request.headers["Authorization"] = "Bearer secret"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        event_hooks={"request": [restore]},
    ) as client:
        response = await client.post("https://first.test/mcp")

    assert response.status_code == 200
    assert seen == [
        ("https://first.test/mcp", "Bearer secret"),
        ("https://second.test/mcp", "Bearer secret"),
    ]
