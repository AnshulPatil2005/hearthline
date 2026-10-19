import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("web_host", "web_url"),
    [
        (None, "http://localhost:5173"),
        ("hearthline-web", "https://hearthline-web.onrender.com"),  # what render.yaml's fromService gives
        ("hearthline-web-x1y2", "https://hearthline-web-x1y2.onrender.com"),
        ("relief.example.org", "https://relief.example.org"),  # a custom domain stays as it is
    ],
)
def test_the_web_url_is_public_on_render(web_host, web_url):
    assert Settings(web_host=web_host, _env_file=None).web_url == web_url
