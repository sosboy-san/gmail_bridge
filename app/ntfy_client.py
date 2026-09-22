import urllib.request

from app.i18n import t


class NtfyClient:
    def __init__(
        self,
        server_url,
        topic,
        token=None,
        timeout=15,
    ):
        self.server_url = server_url.rstrip("/")
        self.topic = topic.strip()
        self.token = token.strip() if token else None
        self.timeout = timeout

        if not self.server_url:
            raise ValueError(
                t('ntfy_client.__init__.1')
            )

        if not self.topic:
            raise ValueError(
                t('ntfy_client.__init__.2')
            )

    def send(
        self,
        message,
        title=None,
        click_url=None,
    ):
        url = (
            f"{self.server_url}/"
            f"{self.topic}"
        )

        request = urllib.request.Request(
            url,
            data=message.encode("utf-8"),
            method="POST",
        )

        if title:
            request.add_header(
                "Title",
                title,
            )

        if click_url:
            request.add_header(
                "Click",
                click_url,
            )

        if self.token:
            request.add_header(
                "Authorization",
                f"Bearer {self.token}",
            )

        with urllib.request.urlopen(
            request,
            timeout=self.timeout,
        ) as response:
            status = response.status

        if not 200 <= status < 300:
            raise RuntimeError(
                t('ntfy_client.send.1', v0=f'{status}')
            )

        return status
