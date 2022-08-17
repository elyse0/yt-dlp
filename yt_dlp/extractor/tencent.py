import functools
import re
import time

from .common import InfoExtractor
from .. import traverse_obj
from ..aes import aes_cbc_encrypt_bytes
from ..utils import determine_ext, int_or_none, urljoin
from ..jsinterp import JSInterpreter


class TencentBaseIE(InfoExtractor):
    """
        Subclasses must set _API_URL, _PLATFORM, _HOST, _REFERER
    """

    def _checksum_callback(self, payload):
        return sum(map(ord, payload))

    def _get_ckey(self, video_id, url, app_version, platform):
        ua = self.get_param('http_headers')['User-Agent']

        payload = (f'|{video_id}|{int(time.time())}|mg3c3b04ba|{app_version}|fae9b9c4fa22ce5f|'
                   f'{platform}|{url[:48]}|{ua.lower()[:48]}||Mozilla|Netscape|Linux x86_64|00|')

        return aes_cbc_encrypt_bytes(
            bytes(f'|{self._checksum_callback(payload)}{payload}', 'utf-8'),
            b'Ok\xda\xa3\x9e/\x8c\xb0\x7f^r-\x9e\xde\xf3\x14',
            b'\x01PJ\xf3V\xe6\x19\xcf.B\xbb\xa6\x8c?p\xf9',
            padding_mode='whitespace').hex().upper()

    def _get_video_api_response(self, video_url, video_id, series_id, subtitle_format, video_format, video_quality):
        app_version = '3.5.57'

        ckey = self._get_ckey(video_id, video_url, app_version, self._PLATFORM)
        query = {
            'vid': video_id,
            'cid': series_id,
            'cKey': ckey,
            'encryptVer': '8.1',
            'spcaptiontype': '1' if subtitle_format == 'vtt' else '0',  # 0 - SRT, 1 - VTT
            'sphls': '1' if video_format == 'hls' else '0',  # 0 - MP4, 1 - HLS
            'dtype': '3' if video_format == 'hls' else '0',  # 0 - MP4, 3 - HLS
            'defn': video_quality,  # '': 480p, 'shd': 720p, 'fhd': 1080p
            'spsrt': '1',  # Enable subtitles
            'sphttps': '1',  # Enable HTTPS
            'otype': 'json',  # Response format: xml, json,
            'spwm': '1',
            'host': self._HOST,  # These next three values are needed for SHD
            'referer': self._REFERER,
            'ehost': video_url,
            'appVer': app_version,
            'platform': self._PLATFORM,
        }

        return self._search_json(r'QZOutputJson=', self._download_webpage(
            self._API_URL, video_id, query=query), 'api_response', video_id)

    def _extract_video_formats_and_subtitles(self, api_response, video_id):
        video_response = api_response['vl']['vi'][0]
        video_width = video_response.get('vw')
        video_height = video_response.get('vh')

        formats, subtitles = [], {}
        for video_format in video_response['ul']['ui']:
            if video_format.get('hls'):
                fmts, subs = self._extract_m3u8_formats_and_subtitles(
                    video_format['url'] + video_format['hls']['pt'], video_id, 'mp4', fatal=False)
                for f in fmts:
                    f['width'] = video_width
                    f['height'] = video_height

                formats.extend(fmts)
                self._merge_subtitles(subs, target=subtitles)
            else:
                formats.append({
                    'url': f'{video_format["url"]}{video_response["fn"]}?vkey={video_response["fvkey"]}',
                    'width': video_width,
                    'height': video_height,
                    'ext': 'mp4',
                })

        return formats, subtitles

    def _extract_video_native_subtitles(self, api_response, subtitles_format):
        subtitles = {}
        for subtitle in traverse_obj(api_response, ('sfl', 'fi')) or ():
            subtitles.setdefault(subtitle['lang'].lower(), []).append({
                'url': subtitle['url'],
                'ext': subtitles_format,
                'protocol': 'm3u8_native' if determine_ext(subtitle['url']) == 'm3u8' else 'http',
            })

        return subtitles

    def _extract_all_video_formats_and_subtitles(self, url, video_id, series_id):
        formats, subtitles = [], {}
        for video_format, subtitle_format, video_quality in (
        ('mp4', 'srt', ''), ('hls', 'vtt', 'shd'), ('hls', 'vtt', 'fhd')):
            api_response = self._get_video_api_response(
                url, video_id, series_id, subtitle_format, video_format, video_quality)

            print(api_response)

            fmts, subs = self._extract_video_formats_and_subtitles(api_response, video_id)
            native_subtitles = self._extract_video_native_subtitles(api_response, subtitle_format)

            formats.extend(fmts)
            self._merge_subtitles(subs, native_subtitles, target=subtitles)

        self._sort_formats(formats)
        return formats, subtitles


class QQIE(TencentBaseIE):
    _VALID_URL = r'https?://(?:v\.)?qq\.com/x/page/(?P<id>\w+)'

    _API_URL = 'https://h5vv6.video.qq.com/getvinfo'
    _PLATFORM = '10901'
    _HOST = 'v.qq.com'
    _REFERER = 'v.qq.com'

    def _checksum_callback(self, payload):
        jsi = JSInterpreter('function x(b){a=0;for(n=0;n<b.length;n++)a=(a<<5)-a+b.charCodeAt(n),a=a&a;return a}')
        return jsi.call_function('x', payload)

    def _real_extract(self, url):
        video_id = self._match_id(url)

        formats, subtitles = self._extract_all_video_formats_and_subtitles(url, video_id, '')
        return {
            'id': video_id,
            'title': '',
            'formats': formats,
            'subtitles': subtitles,
        }


class WeTvBaseIE(TencentBaseIE):
    _VALID_URL_BASE = r'https?://(?:www\.)?wetv\.vip/(?:[^?#]+/)?play'

    _API_URL = 'https://play.wetv.vip/getvinfo'
    _PLATFORM = '4830201'
    _HOST = 'wetv.vip'
    _REFERER = 'wetv.vip'

    def _get_webpage_metadata(self, webpage, video_id):
        return self._parse_json(
            traverse_obj(self._search_nextjs_data(webpage, video_id), ('props', 'pageProps', 'data')),
            video_id, fatal=False)


class WeTvEpisodeIE(WeTvBaseIE):
    IE_NAME = 'wetv:episode'
    _VALID_URL = WeTvBaseIE._VALID_URL_BASE + r'/(?P<series_id>\w+)(?:-[^?#]+)?/(?P<id>\w+)(?:-[^?#]+)?'

    _TESTS = [{
        'url': 'https://wetv.vip/en/play/air11ooo2rdsdi3-Cute-Programmer/v0040pr89t9-EP1-Cute-Programmer',
        'md5': '0c70fdfaa5011ab022eebc598e64bbbe',
        'info_dict': {
            'id': 'v0040pr89t9',
            'ext': 'mp4',
            'title': 'EP1: Cute Programmer',
            'description': 'md5:e87beab3bf9f392d6b9e541a63286343',
            'thumbnail': r're:^https?://[^?#]+air11ooo2rdsdi3',
            'series': 'Cute Programmer',
            'episode': 'Episode 1',
            'episode_number': 1,
            'duration': 2835,
        },
    }, {
        'url': 'https://wetv.vip/en/play/u37kgfnfzs73kiu/p0039b9nvik',
        'md5': '3b3c15ca4b9a158d8d28d5aa9d7c0a49',
        'info_dict': {
            'id': 'p0039b9nvik',
            'ext': 'mp4',
            'title': 'EP1: You Are My Glory',
            'description': 'md5:831363a4c3b4d7615e1f3854be3a123b',
            'thumbnail': r're:^https?://[^?#]+u37kgfnfzs73kiu',
            'series': 'You Are My Glory',
            'episode': 'Episode 1',
            'episode_number': 1,
            'duration': 2454,
        },
    }, {
        'url': 'https://wetv.vip/en/play/lcxgwod5hapghvw-WeTV-PICK-A-BOO/i0042y00lxp-Zhao-Lusi-Describes-The-First-Experiences-She-Had-In-Who-Rules-The-World-%7C-WeTV-PICK-A-BOO',
        'md5': '71133f5c2d5d6cad3427e1b010488280',
        'info_dict': {
            'id': 'i0042y00lxp',
            'ext': 'mp4',
            'title': 'md5:f7a0857dbe5fbbe2e7ad630b92b54e6a',
            'description': 'md5:76260cb9cdc0ef76826d7ca9d92fadfa',
            'thumbnail': r're:^https?://[^?#]+lcxgwod5hapghvw',
            'series': 'WeTV PICK-A-BOO',
            'episode': 'Episode 0',
            'episode_number': 0,
            'duration': 442,
        },
    }]

    def _real_extract(self, url):
        video_id, series_id = self._match_valid_url(url).group('id', 'series_id')
        webpage = self._download_webpage(url, video_id)

        formats, subtitles = self._extract_all_video_formats_and_subtitles(url, video_id, series_id)
        webpage_metadata = self._get_webpage_metadata(webpage, video_id)

        return {
            'id': video_id,
            'title': (self._og_search_title(webpage) or
                      traverse_obj(webpage_metadata, ('coverInfo', 'title'))).replace('_Watch online', ''),
            'description': (
                traverse_obj(webpage_metadata, ('coverInfo', 'description') or self._og_search_description(webpage))),
            'formats': formats,
            'subtitles': subtitles,
            'thumbnail': self._og_search_thumbnail(webpage),
            'duration': int_or_none(traverse_obj(webpage_metadata, ('videoInfo', 'duration'))),
            'series': traverse_obj(webpage_metadata, ('coverInfo', 'title')),
            'episode_number': int_or_none(traverse_obj(webpage_metadata, ('videoInfo', 'episode'))),
        }


class WeTvSeriesIE(WeTvBaseIE):
    _VALID_URL = WeTvBaseIE._VALID_URL_BASE + r'/(?P<id>\w+)(?:-[^/?#]+)?/?(?:[?#]|$)'

    _TESTS = [{
        'url': 'https://wetv.vip/play/air11ooo2rdsdi3-Cute-Programmer',
        'info_dict': {
            'id': 'air11ooo2rdsdi3',
            'title': 'Cute Programmer',
            'description': 'md5:e87beab3bf9f392d6b9e541a63286343',
        },
        'playlist_count': 30,
    }, {
        'url': 'https://wetv.vip/en/play/u37kgfnfzs73kiu-You-Are-My-Glory',
        'info_dict': {
            'id': 'u37kgfnfzs73kiu',
            'title': 'You Are My Glory',
            'description': 'md5:831363a4c3b4d7615e1f3854be3a123b',
        },
        'playlist_count': 32,
    }]

    def _real_extract(self, url):
        series_id = self._match_id(url)
        webpage = self._download_webpage(url, series_id)
        webpage_metadata = self._get_webpage_metadata(webpage, series_id)

        episode_paths = (re.findall(r'<a[^>]+class="play-video__link"[^>]+href="(?P<path>[^"]+)', webpage)
                         or [f'/{series_id}/{episode["vid"]}' for episode in webpage_metadata.get('videoList')])

        return self.playlist_from_matches(
            episode_paths, series_id, ie=WeTvEpisodeIE, getter=functools.partial(urljoin, url),
            title=traverse_obj(webpage_metadata, ('coverInfo', 'title')) or self._og_search_title(webpage),
            description=traverse_obj(webpage_metadata, ('coverInfo', 'description')) or self._og_search_description(
                webpage))
