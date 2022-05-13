import re

from .common import InfoExtractor
from ..utils import (
    extract_attributes,
    determine_ext,
    jwt_decode_hs256
)


class BFMTVBaseIE(InfoExtractor):
    _VALID_URL_BASE = r'https?://(?:www\.)?bfmtv\.com/'
    _VALID_URL_TMPL = _VALID_URL_BASE + r'(?:[^/]+/)*[^/?&#]+_%s[A-Z]-(?P<id>\d{12})\.html'
    _VIDEO_BLOCK_REGEX = r'(<div[^>]+class="video_block"[^>]*>)'
    BRIGHTCOVE_URL_TEMPLATE = 'http://players.brightcove.net/%s/%s_default/index.html?videoId=%s'

    def _brightcove_url_result(self, video_id, video_block):
        account_id = video_block.get('accountid') or '876450612001'
        player_id = video_block.get('playerid') or 'I2qBTln4u'
        return self.url_result(
            self.BRIGHTCOVE_URL_TEMPLATE % (account_id, player_id, video_id),
            'BrightcoveNew', video_id)


class BFMTVIE(BFMTVBaseIE):
    IE_NAME = 'bfmtv'
    _VALID_URL = BFMTVBaseIE._VALID_URL_TMPL % 'V'
    _TESTS = [{
        'url': 'https://www.bfmtv.com/politique/emmanuel-macron-l-islam-est-une-religion-qui-vit-une-crise-aujourd-hui-partout-dans-le-monde_VN-202010020146.html',
        'info_dict': {
            'id': '6196747868001',
            'ext': 'mp4',
            'title': 'Emmanuel Macron: "L\'Islam est une religion qui vit une crise aujourd’hui, partout dans le monde"',
            'description': 'Le Président s\'exprime sur la question du séparatisme depuis les Mureaux, dans les Yvelines.',
            'uploader_id': '876450610001',
            'upload_date': '20201002',
            'timestamp': 1601629620,
        },
    }]

    def _real_extract(self, url):
        bfmtv_id = self._match_id(url)
        webpage = self._download_webpage(url, bfmtv_id)
        video_block = extract_attributes(self._search_regex(
            self._VIDEO_BLOCK_REGEX, webpage, 'video block'))
        return self._brightcove_url_result(video_block['videoid'], video_block)


class BFMTVLiveIE(BFMTVIE):
    IE_NAME = 'bfmtv:live'
    _VALID_URL = BFMTVBaseIE._VALID_URL_BASE + '(?P<id>(?:[^/]+/)?en-direct)'
    _TESTS = [{
        'url': 'https://www.bfmtv.com/en-direct/',
        'info_dict': {
            'id': '5615950982001',
            'ext': 'mp4',
            'title': r're:^le direct BFMTV WEB \d{4}-\d{2}-\d{2} \d{2}:\d{2}$',
            'uploader_id': '876450610001',
            'upload_date': '20171018',
            'timestamp': 1508329950,
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'https://www.bfmtv.com/economie/en-direct/',
        'only_matching': True,
    }]


class BFMTVArticleIE(BFMTVBaseIE):
    IE_NAME = 'bfmtv:article'
    _VALID_URL = BFMTVBaseIE._VALID_URL_TMPL % 'A'
    _TESTS = [{
        'url': 'https://www.bfmtv.com/sante/covid-19-un-responsable-de-l-institut-pasteur-se-demande-quand-la-france-va-se-reconfiner_AV-202101060198.html',
        'info_dict': {
            'id': '202101060198',
            'title': 'Covid-19: un responsable de l\'Institut Pasteur se demande "quand la France va se reconfiner"',
            'description': 'md5:947974089c303d3ac6196670ae262843',
        },
        'playlist_count': 2,
    }, {
        'url': 'https://www.bfmtv.com/international/pour-bolsonaro-le-bresil-est-en-faillite-mais-il-ne-peut-rien-faire_AD-202101060232.html',
        'only_matching': True,
    }, {
        'url': 'https://www.bfmtv.com/sante/covid-19-oui-le-vaccin-de-pfizer-distribue-en-france-a-bien-ete-teste-sur-des-personnes-agees_AN-202101060275.html',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        bfmtv_id = self._match_id(url)
        webpage = self._download_webpage(url, bfmtv_id)

        entries = []
        for video_block_el in re.findall(self._VIDEO_BLOCK_REGEX, webpage):
            video_block = extract_attributes(video_block_el)
            video_id = video_block.get('videoid')
            if not video_id:
                continue
            entries.append(self._brightcove_url_result(video_id, video_block))

        return self.playlist_result(
            entries, bfmtv_id, self._og_search_title(webpage, fatal=False),
            self._html_search_meta(['og:description', 'description'], webpage))


class BFMPlayVideoIE(InfoExtractor):
    IE_NAME = 'rmc-bfmplay'
    _VALID_URL = r'https?://(?:www\.)?rmcbfmplay\.com/.*\?contentId=(?P<id>.*)&.*'
    _TESTS = []

    def _get_token(self, video_id, client_id):
        url = 'https://sso-client.rmcbfmplay.com/cas/oidc/authorize'

        self._get_cookies('https://sso-client.rmcbfmplay.com')

        response = self._download_webpage(
            url, video_id, query={
                'client_id': client_id,
                'scope': 'openid',
                'response_type': 'token',
                'redirect_uri': 'https://www.rmcbfmplay.com',
                'token': 'true',
                'gateway': 'true'
            })

        return jwt_decode_hs256(response).get('tu')

    def _extract_video(self, video_id):
        # FIXME: Replace your CLIENT_ID
        token = self._get_token(video_id, 'REPLACE_HERE_YOUR_CLIENT_ID')

        response = self._download_json(
            "https://ws-backendtv.rmcbfmplay.com/gaia-core/rest/api/web/v2/content/{}/options".format(video_id),
            video_id=video_id, query={
                'app': 'bfmrmc',
                'device': 'browser',
                'universe': 'PROVIDER',
                'token': token
            })[0]

        title = response.get('title')

        formats, subtitles = [], []
        for offer in response.get('offers'):
            streams = offer.get('streams')

            for stream in streams:
                video_url = stream.get('url')

                ext = determine_ext(video_url)
                if ext == "m3u8":
                    fmts, subs = self._extract_m3u8_formats_and_subtitles(video_url, video_id, 'mp4', fatal=False)
                    formats.extend(fmts)
                    self._merge_subtitles(subs, target=subtitles)
                elif ext == 'mpd':
                    fmts, subs = self._extract_mpd_formats_and_subtitles(video_url, video_id, fatal=False)
                    formats.extend(fmts)
                    self._merge_subtitles(subs, target=subtitles)
                elif ext == 'ism':
                    fmts, subs = self._extract_ism_formats_and_subtitles(video_url, video_id, fatal=False)
                    formats.extend(fmts)
                    self._merge_subtitles(subs, target=subtitles)

        return {
            'id': video_id,
            'title': title,
            'formats': formats,
            'subtitles': subtitles,
        }

    def _real_extract(self, url):
        video_id = self._match_id(url)

        return self._extract_video(video_id)
