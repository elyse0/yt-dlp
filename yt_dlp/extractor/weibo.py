import json
import random
import re

from .common import InfoExtractor
from ..utils import (
    determine_ext,
    int_or_none,
    js_to_json,
    strip_jsonp,
    traverse_obj,
    urlencode_postdata,
)


class WeiboIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?weibo\.com/[0-9]+/(?P<id>[a-zA-Z0-9]+)'
    _TESTS = [{
        'url': 'https://weibo.com/6275294458/Fp6RGfbff?type=comment',
        'info_dict': {
            'id': 'Fp6RGfbff',
            'ext': 'mp4',
            'title': 'You should have servants to massage you, pamper you. 💆🏻\u200d♂️',
            'uploader': 'Hosico_猫',
            'thumbnail': 'http://wx3.sinaimg.cn/orj480/006QGuKKly1fk8gte6pmnj30zk0k0t9i.jpg',
            'duration': 43,
        },
    }, {
        'url': 'https://weibo.com/5992567671/M2nIRoZJn?pagetype=hot',
        'info_dict': {
            'id': 'M2nIRoZJn',
            'ext': 'mp4',
            'title': '#野生动物##动物# ～雪地里的北极熊母子～',
            'uploader': '大自然震撼之美',
            'thumbnail': 'http://wx3.sinaimg.cn/orj480/006xycBhly8h5gbfdx8pkj30k00soaaz.jpg',
            'duration': 31,
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        api_response = self._download_json(f'https://weibo.com/ajax/statuses/show?id={video_id}', video_id)
        media_info = api_response['page_info']['media_info']

        formats, subtitles = [], {}
        for format_id in ('stream_url', 'mp4_sd_url', 'h265_mp4_ld', 'h265_mp4_hd', 'stream_url_hd', 'mp4_hd_url',
                          'inch_4_mp4_hd', 'inch_5_mp4_hd', 'inch_5_5_mp4_hd', 'mp4_720p_mp4', 'hevc_mp4_720p'):
            format_url = media_info.get(format_id)
            if not format_url:
                continue

            ext = determine_ext(format_url)
            if ext == 'm3u8':
                fmts, subs = self._extract_m3u8_formats_and_subtitles(
                    format_url, video_id, 'mp4', entry_protocol='m3u8_native', m3u8_id=format_id, fatal=False)
                formats.extend(fmts)
                self._merge_subtitles(subs, target=subtitles)
            else:
                formats.append({
                    'format_id': format_id,
                    'url': format_url
                })

        return {
            'id': video_id,
            'title': media_info.get('next_title') or media_info.get('kol_title'),
            'uploader': media_info.get('author_name'),
            'formats': formats,
            'subtitles': subtitles,
            'thumbnail': traverse_obj(api_response, ('page_info', 'page_pic')),
            'duration': media_info.get('duration')
        }


class WeiboTvIE(InfoExtractor):
    IE_NAME = 'weibo:tv'
    _VALID_URL = r'https?://(?:www\.)?weibo\.com/tv/show/(?P<id>[\w:]+)'

    _TESTS = [{
        'url': 'https://weibo.com/tv/show/1034:4784955918843950',
        'info_dict': {
            'id': '1034:4784955918843950',
            'title': '每天需要搬多少砖，才能够拥有她？',
            'ext': 'mp4',
            'thumbnail': 'http://wx4.sinaimg.cn/large/0079seP1ly1h3mppnrcmnj30no0dcq4r.jpg',
            'duration': 202.222,
            'uploader': '姚希妍',
            'timestamp': 1656305854,
            'upload_date': '20220627',
        },
    }, {
        'url': 'https://weibo.com/tv/show/1034:4765854085349511',
        'info_dict': {
            'id': '1034:4765854085349511',
            'title': 'glass house mountain 爬山vlog',
            'ext': 'mp4',
            'thumbnail': 'http://wx1.sinaimg.cn/orj480/cf56f4e7gy1h1xrw4ul8tj21hc0u0qc1.jpg',
            'duration': 69.518,
            'uploader': '毛毛虫Claire',
            'timestamp': 1651751622,
            'upload_date': '20220505',
        },
    }]

    def _check_passport(self, url, video_id):
        if self._get_cookies('https://weibo.com').get('SUB'):
            return

        webpage, urlh = self._download_webpage_handle(url, video_id)
        visitor_url = urlh.geturl()

        if 'passport.weibo.com' in visitor_url:
            # first visit
            visitor_data = self._download_json(
                'https://passport.weibo.com/visitor/genvisitor', video_id,
                note='Generating first-visit data',
                transform_source=strip_jsonp,
                headers={'Referer': visitor_url},
                data=urlencode_postdata({
                    'cb': 'gen_callback',
                    'fp': json.dumps({
                        'os': '2',
                        'browser': 'Gecko104,0,0,0',
                        'fonts': 'undefined',
                        'screenInfo': '1440*900*24',
                        'plugins': 'Portable Document Format::internal-pdf-viewer::PDF Viewer|Portable Document Format::internal-pdf-viewer::Chrome PDF Viewer',
                    }),
                }))

            tid = visitor_data['data']['tid']
            cnfd = '%03d' % visitor_data['data']['confidence']

            self._download_webpage(
                'https://passport.weibo.com/visitor/visitor', video_id,
                note='Running first-visit callback',
                query={
                    'a': 'incarnate',
                    't': tid,
                    'w': 2,
                    'c': cnfd,
                    'cb': 'cross_domain',
                    'from': 'weibo',
                    '_rand': random.random(),
                })

    def _real_extract(self, url):
        video_id = self._match_id(url)
        self._check_passport(url, video_id)

        request_data = json.dumps({"Component_Play_Playinfo": {"oid": video_id}}, separators=(',', ':'))

        video_info = self._download_json(
            'https://weibo.com/tv/api/component', video_id, data=bytes(f'data={request_data}', 'utf-8'),
            query={'page': f'/tv/show/{video_id}'}, headers={'Referer': url})['data']['Component_Play_Playinfo']

        formats = []
        for format_id in video_info['urls']:
            formats.append({
                'format_id': format_id,
                'url': f'https:{video_info["urls"][format_id]}',
                'height': int_or_none(self._search_regex(r'(\d+)P$', format_id, 'format height', default=None)),
            })

        self._sort_formats(formats)
        return {
            'id': video_id,
            'title': video_info['title'],
            'formats': formats,
            'thumbnail': video_info.get('cover_image'),
            'duration': video_info.get('duration_time'),
            'uploader': video_info.get('author'),
            'timestamp': video_info.get('real_date'),
        }


class WeiboMobileIE(InfoExtractor):
    _VALID_URL = r'https?://m\.weibo\.cn/status/(?P<id>[0-9]+)(\?.+)?'
    _TESTS = [{
        'url': 'https://m.weibo.cn/status/4189191225395228?wm=3333_2001&sourcetype=weixin&featurecode=newtitle&from=singlemessage&isappinstalled=0',
        'info_dict': {
            'id': '4189191225395228',
            'ext': 'mp4',
            'title': '午睡当然是要甜甜蜜蜜的啦',
            'uploader': '柴犬柴犬',
        },
    }, {
        'url': 'https://m.weibo.cn/status/4800376257119180',
        'info_dict': {
            'id': '4800376257119180',
            'ext': 'mp4',
            'title': '(G)I-DLE',
            'uploader': 'Summer__Sama',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        # to get Referer url for genvisitor
        webpage = self._download_webpage(url, video_id, note='visit the page')

        weibo_info = self._parse_json(self._search_regex(
            r'var\s+\$render_data\s*=\s*\[({.*})\]\[0\]\s*\|\|\s*{};',
            webpage, 'js_code', flags=re.DOTALL),
            video_id, transform_source=js_to_json)

        status_data = weibo_info.get('status', {})
        page_info = status_data.get('page_info')
        title = status_data['status_title']
        uploader = status_data.get('user', {}).get('screen_name')

        formats = [{
            'format_id': 'stream_url',
            'url': page_info['media_info']['stream_url']
        }]
        for video_quality in ('mp4_ld_mp4', 'mp4_hd_mp4', 'mp4_720p_mp4'):
            video_url = traverse_obj(page_info, ('urls', video_quality))
            if video_url:
                formats.append({
                    'format_id': video_quality,
                    'url': video_url,
                })

        return {
            'id': video_id,
            'title': title,
            'uploader': uploader,
            'formats': formats,
        }
