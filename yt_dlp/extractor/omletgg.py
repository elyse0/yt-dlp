from .common import InfoExtractor
from ..utils import WebSocketsWrapper


class OmletGGIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?omlet\.gg/stream/(?P<id>[\w-]+)'

    _TESTS = [{
        'url': 'http://omlet.gg/stream/yetimusiccity',
        'info_dict': {
            'id': 'yetimusiccity',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)

        ws = WebSocketsWrapper('ws://omlet.gg/readolydevice', {
            'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/110.0',
            'Cookie': 'identity=e0r+IFUxF4jc1lbvX2IVSPlXNyy3; __stripe_mid=33d8670f-a46a-49e6-a103-a94b51232e161a9a2d; __stripe_sid=8c842a87-12a1-42e0-b339-7790df5beaf68dfc38',
            'Origin': 'http://omlet.gg',
            'Host': 'http://omlet.gg',
            'Sec-WebSocket-Key': 'CF9FzsU/rBcLVuDn0QZCCA==',
            'Sec-WebSocket-Version': 13,
            'Sec-WebSocket-Extensions': 'permessage-deflate',
            'Upgrade': 'websocket',
            'Accept-Language': 'en-US,fr;q=0.7,en;q=0.3',
        })

        while True:
            recv = ws.recv()
            if not recv:
                continue
            data = self._parse_json(recv, video_id, fatal=False)
            if not data or not isinstance(data, dict):
                continue

            print(data)
            break

        return {
            'id': video_id,
        }
