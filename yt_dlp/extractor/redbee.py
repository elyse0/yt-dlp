import json
import uuid
import re
import time

from .common import InfoExtractor
from ..compat import compat_urllib_parse_urlencode
from ..utils import (
    ExtractorError,
    float_or_none,
    int_or_none,
    strip_or_none,
    try_get,
    unified_timestamp,
)


class RedBeeIE(InfoExtractor):
    _VALID_URL = r'redbee:(?P<customer>[\w_-]+):(?P<business_unit>[\w_-]+):(?P<asset_id>[\w_-]+)'
    _DEVICE_ID = str(uuid.uuid4())
    # https://apidocs.emp.ebsd.ericsson.net
    _SERVICE_URL = 'https://exposure.api.redbee.live'

    def _get_bearer_token(self, asset_id, customer, business_unit, auth_type='anonymous', **args):
        request = {
            'deviceId': self._DEVICE_ID,
            'device': {
                'deviceId': self._DEVICE_ID,
                'name': 'Mozilla Firefox 102',
                'type': 'WEB',
            },
        }
        if auth_type == 'gigyaLogin':
            request['jwt'] = args['jwt']

        return self._download_json(
            f'{self._SERVICE_URL}/v2/customer/{customer}/businessunit/{business_unit}/auth/{auth_type}',
            asset_id, data=json.dumps(request).encode('utf-8'), headers={
                'Content-Type': 'application/json;charset=utf-8'
            })['sessionToken']

    def _get_entitlement_formats_and_subtitles(self, asset_id, customer, business_unit, bearer_token):
        api_response = self._download_json(
            f'{self._SERVICE_URL}/v2/customer/{customer}/businessunit/{business_unit}/entitlement/{asset_id}/play',
            asset_id, headers={
                'Authorization': f'Bearer {bearer_token}',
                'Accept': 'application/json, text/plain, */*'
            })

        formats, subtitles = [], {}
        for format in api_response['formats']:
            if not format.get('mediaLocator'):
                continue

            fmts, subs = [], {}
            if format.get('format') == 'DASH':
                fmts, subs = self._extract_mpd_formats_and_subtitles(
                    format['mediaLocator'], asset_id, fatal=False)
            elif format.get('format') == 'SMOOTHSTREAMING':
                fmts, subs = self._extract_ism_formats_and_subtitles(
                    format['mediaLocator'], asset_id, fatal=False)
            elif format.get('format') == 'HLS':
                fmts, subs = self._extract_m3u8_formats_and_subtitles(
                    format['mediaLocator'], asset_id, fatal=False)

            formats.extend(fmts)
            self._merge_subtitles(subs, target=subtitles)

        self._sort_formats(formats)
        return formats, subtitles

    def _real_extract(self, url):
        customer, business_unit, asset_id = self._match_valid_url(url).group('customer', 'business_unit', 'asset_id')

        formats, subtitles = self._get_entitlement_formats_and_subtitles(
            asset_id, customer, business_unit, self._get_bearer_token(asset_id, customer, business_unit))

        return {
            'id': asset_id,
            'formats': formats,
            'subtitles': subtitles,
        }


class ParliamentLiveUKIE(RedBeeIE):
    IE_NAME = 'parliamentlive.tv'
    IE_DESC = 'UK parliament videos'
    _VALID_URL = r'(?i)https?://(?:www\.)?parliamentlive\.tv/Event/Index/(?P<id>[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12})'

    _TESTS = [{
        'url': 'http://parliamentlive.tv/Event/Index/c1e9d44d-fd6c-4263-b50f-97ed26cc998b',
        'info_dict': {
            'id': 'c1e9d44d-fd6c-4263-b50f-97ed26cc998b',
            'ext': 'mp4',
            'title': 'Home Affairs Committee',
            'timestamp': 1395153872,
            'upload_date': '20140318',
            'thumbnail': r're:https?://[^?#]+c1e9d44d-fd6c-4263-b50f-97ed26cc998b[^/]*/thumbnail',
        },
    }, {
        'url': 'http://parliamentlive.tv/event/index/3f24936f-130f-40bf-9a5d-b3d6479da6a4',
        'only_matching': True,
    }, {
        'url': 'https://parliamentlive.tv/Event/Index/27cf25e4-e77b-42a3-93c5-c815cd6d7377',
        'info_dict': {
            'id': '27cf25e4-e77b-42a3-93c5-c815cd6d7377',
            'ext': 'mp4',
            'title': 'House of Commons',
            'timestamp': 1658392447,
            'upload_date': '20220721',
            'thumbnail': r're:https?://[^?#]+27cf25e4-e77b-42a3-93c5-c815cd6d7377[^/]*/thumbnail',
        },
    }]

    _REDBEE_CUSTOMER = 'UKParliament'
    _REDBEE_BUSINESS_UNIT = 'ParliamentLive'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        video_info = self._download_json(f'https://www.parliamentlive.tv/Event/GetShareVideo/{video_id}', video_id)

        formats, subtitles = self._get_entitlement_formats_and_subtitles(
            video_id, self._REDBEE_CUSTOMER, self._REDBEE_BUSINESS_UNIT,
            self._get_bearer_token(video_id, self._REDBEE_CUSTOMER, self._REDBEE_BUSINESS_UNIT))

        return {
            'id': video_id,
            'title': video_info['event']['title'],
            'formats': formats,
            'subtitles': subtitles,
            'timestamp': unified_timestamp(try_get(video_info, lambda x: x['event']['publishedStartTime'])),
            'thumbnail': video_info.get('thumbnailUrl'),
        }


class RTBFIE(RedBeeIE):
    _VALID_URL = r'''(?x)
        https?://(?:www\.)?rtbf\.be/
        (?:
            video/[^?]+\?.*\bid=|
            ouftivi/(?:[^/]+/)*[^?]+\?.*\bvideoId=|
            auvio/[^/]+\?.*\b(?P<live>l)?id=
        )(?P<id>\d+)'''
    _NETRC_MACHINE = 'rtbf'
    _TESTS = [{
        'url': 'https://www.rtbf.be/video/detail_les-diables-au-coeur-episode-2?id=1921274',
        'md5': '8c876a1cceeb6cf31b476461ade72384',
        'info_dict': {
            'id': '1921274',
            'ext': 'mp4',
            'title': 'Les Diables au coeur (épisode 2)',
            'description': '(du 25/04/2014)',
            'duration': 3099.54,
            'upload_date': '20140425',
            'timestamp': 1398456300,
        },
        'skip': 'No longer available',
    }, {
        # geo restricted
        'url': 'http://www.rtbf.be/ouftivi/heros/detail_scooby-doo-mysteres-associes?id=1097&videoId=2057442',
        'only_matching': True,
    }, {
        'url': 'http://www.rtbf.be/ouftivi/niouzz?videoId=2055858',
        'only_matching': True,
    }, {
        'url': 'http://www.rtbf.be/auvio/detail_jeudi-en-prime-siegfried-bracke?id=2102996',
        'only_matching': True,
    }, {
        # Live
        'url': 'https://www.rtbf.be/auvio/direct_pure-fm?lid=134775',
        'only_matching': True,
    }, {
        # Audio
        'url': 'https://www.rtbf.be/auvio/detail_cinq-heures-cinema?id=2360811',
        'only_matching': True,
    }, {
        # With Subtitle
        'url': 'https://www.rtbf.be/auvio/detail_les-carnets-du-bourlingueur?id=2361588',
        'only_matching': True,
    }, {
        'url': 'https://www.rtbf.be/auvio/detail_investigation?id=2921926',
        'md5': 'd5d11bb62169fef38d7ce7ac531e034f',
        'info_dict': {
            'id': '2921926',
            'ext': 'mp4',
            'title': 'Le handicap un confinement perpétuel - Maladie de Lyme',
            'description': 'md5:dcbd5dcf6015488c9069b057c15ccc52',
            'duration': 5258.8,
            'upload_date': '20220727',
            'timestamp': 1658934000,
            'series': '#Investigation',
            'thumbnail': r're:^https?://[^?&]+\.jpg$',
        },
    }, {
        'url': 'https://www.rtbf.be/auvio/detail_la-belgique-criminelle?id=2920492',
        'md5': '054f9f143bc79c89647c35e5a7d35fa8',
        'info_dict': {
            'id': '2920492',
            'ext': 'mp4',
            'title': '04 - Le crime de la rue Royale',
            'description': 'md5:0c3da1efab286df83f2ab3f8f96bd7a6',
            'duration': 1574.6,
            'upload_date': '20220723',
            'timestamp': 1658596887,
            'series': 'La Belgique criminelle - TV',
            'thumbnail': r're:^https?://[^?&]+\.jpg$',
        },
    }]
    _IMAGE_HOST = 'http://ds1.ds.static.rtbf.be'
    _PROVIDERS = {
        'YOUTUBE': 'Youtube',
        'DAILYMOTION': 'Dailymotion',
        'VIMEO': 'Vimeo',
    }
    _QUALITIES = [
        ('mobile', 'SD'),
        ('web', 'MD'),
        ('high', 'HD'),
    ]
    _LOGIN_URL = 'https://login.rtbf.be/accounts.login'
    _GIGYA_API_KEY = '3_kWKuPgcdAybqnqxq_MvHVk0-6PN8Zk8pIIkJM_yXOu-qLPDDsGOtIDFfpGivtbeO'
    _LOGIN_COOKIE_ID = f'glt_{_GIGYA_API_KEY}'
    _REDBEE_CUSTOMER = 'RTBF'
    _REDBEE_BUSINESS_UNIT = 'Auvio'

    def _perform_login(self, username, password):
        if self._get_cookies(self._LOGIN_URL).get(self._LOGIN_COOKIE_ID):
            return

        self._set_cookie('.rtbf.be', 'gmid', 'gmid.ver4', secure=True, expire_time=time.time() + 3600)

        login_response = self._download_json(
            'https://login.rtbf.be/accounts.login', None, data=compat_urllib_parse_urlencode({
                'loginID': username,
                'password': password,
                'APIKey': self._GIGYA_API_KEY,
                'targetEnv': 'jssdk',
                'sessionExpiration': '-2',
            }).encode('utf-8'), headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            })

        if login_response['statusCode'] != 200:
            raise ExtractorError('Login failed. Server message: %s' % login_response['errorMessage'], expected=True)

        self._set_cookie('.rtbf.be', self._LOGIN_COOKIE_ID, login_response['sessionInfo']['login_token'],
                         secure=True, expire_time=time.time() + 3600)
        if not self._get_cookies(self._LOGIN_URL).get(self._LOGIN_COOKIE_ID):
            raise ExtractorError(f'Login succeeded but did not set {self._LOGIN_COOKIE_ID} cookie')

    def _get_redbee_formats_and_subtitles(self, url, media_id):
        login_token = self._get_cookies(url).get(self._LOGIN_COOKIE_ID)
        if not login_token:
            self.raise_login_required()

        session_jwt = self._download_json(
            "https://login.rtbf.be/accounts.getJWT", media_id, query={
                'login_token': login_token.value,
                'APIKey': self._GIGYA_API_KEY,
                'sdk': 'js_latest',
                'authMode': 'cookie',
                'pageURL': url,
                'sdkBuild': '13273',
                'format': 'json',
            })['id_token']

        return self._get_entitlement_formats_and_subtitles(
            media_id, self._REDBEE_CUSTOMER, self._REDBEE_BUSINESS_UNIT,
            self._get_bearer_token(
                media_id, self._REDBEE_CUSTOMER, self._REDBEE_BUSINESS_UNIT, 'gigyaLogin', jwt=session_jwt))

    def _real_extract(self, url):
        live, media_id = self._match_valid_url(url).groups()
        embed_page = self._download_webpage(
            'https://www.rtbf.be/auvio/embed/' + ('direct' if live else 'media'),
            media_id, query={'id': media_id})
        data = self._parse_json(self._html_search_regex(
            r'data-media="([^"]+)"', embed_page, 'media data'), media_id)

        error = data.get('error')
        if error:
            raise ExtractorError('%s said: %s' % (self.IE_NAME, error), expected=True)

        provider = data.get('provider')
        if provider in self._PROVIDERS:
            return self.url_result(data['url'], self._PROVIDERS[provider])

        title = data['subtitle']
        is_live = data.get('isLive')
        height_re = r'-(\d+)p\.'
        formats = []

        m3u8_url = data.get('urlHlsAes128') or data.get('urlHls')
        if m3u8_url:
            formats.extend(self._extract_m3u8_formats(
                m3u8_url, media_id, 'mp4', m3u8_id='hls', fatal=False))

        fix_url = lambda x: x.replace('//rtbf-vod.', '//rtbf.') if '/geo/drm/' in x else x
        http_url = data.get('url')
        if formats and http_url and re.search(height_re, http_url):
            http_url = fix_url(http_url)
            for m3u8_f in formats[:]:
                height = m3u8_f.get('height')
                if not height:
                    continue
                f = m3u8_f.copy()
                del f['protocol']
                f.update({
                    'format_id': m3u8_f['format_id'].replace('hls-', 'http-'),
                    'url': re.sub(height_re, '-%dp.' % height, http_url),
                })
                formats.append(f)
        else:
            sources = data.get('sources') or {}
            for key, format_id in self._QUALITIES:
                format_url = sources.get(key)
                if not format_url:
                    continue
                height = int_or_none(self._search_regex(
                    height_re, format_url, 'height', default=None))
                formats.append({
                    'format_id': format_id,
                    'url': fix_url(format_url),
                    'height': height,
                })

        mpd_url = data.get('urlDash')
        if mpd_url and (self.get_param('allow_unplayable_formats') or not data.get('drm')):
            formats.extend(self._extract_mpd_formats(
                mpd_url, media_id, mpd_id='dash', fatal=False))

        audio_url = data.get('urlAudio')
        if audio_url:
            formats.append({
                'format_id': 'audio',
                'url': audio_url,
                'vcodec': 'none',
            })
        self._sort_formats(formats)

        subtitles = {}
        for track in (data.get('tracks') or {}).values():
            sub_url = track.get('url')
            if not sub_url:
                continue
            subtitles.setdefault(track.get('lang') or 'fr', []).append({
                'url': sub_url,
            })

        if not formats:
            fmts, subs = self._get_redbee_formats_and_subtitles(url, media_id)
            formats.extend(fmts)
            self._merge_subtitles(subs, target=subtitles)

        return {
            'id': media_id,
            'formats': formats,
            'title': title,
            'description': strip_or_none(data.get('description')),
            'thumbnail': data.get('thumbnail'),
            'duration': float_or_none(data.get('realDuration')),
            'timestamp': int_or_none(data.get('liveFrom')),
            'series': data.get('programLabel'),
            'subtitles': subtitles,
            'is_live': is_live,
        }
