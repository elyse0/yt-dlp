import re

from .common import InfoExtractor
from ..utils import (
    strip_or_none,
    xpath_text,
)


class NhaccuatuiBaseIE(InfoExtractor):
    _VALID_URL_BASE = r'https?://(?:www\.)?nhaccuatui\.com'
    _RESOURCE_ID = r'/[^/#?]+\.(?P<id>[\w-]+).html'

    def _get_api_response(self, webpage, resource_id):
        return self._download_xml(self._html_search_regex(
            r'player.peConfig.xmlURL\s*=\s*"(?P<video_url>[^"]+)', webpage, 'video_url'), video_id=resource_id)


class NhaccuatuiTrackIE(NhaccuatuiBaseIE):
    _VALID_URL = NhaccuatuiBaseIE._VALID_URL_BASE + r'/bai-hat' + NhaccuatuiBaseIE._RESOURCE_ID

    _TESTS = [{
        'url': 'https://www.nhaccuatui.com/bai-hat/anh-lo-cho-em-het-dam-vinh-hung-ft-ricky-star.6kR2oGcAn87W.html',
        'md5': 'ace237d7859d5ffa2a1bf1a0fcb72207',
        'info_dict': {
            'id': '6kR2oGcAn87W',
            'ext': 'mp3',
            'title': 'Anh Lo Cho Em Hết',
            'thumbnail': r're:https?://.*\.jpg$',
            'artist': 'Đàm Vĩnh Hưng, Ricky Star',
        },
    }, {
        'url': 'https://www.nhaccuatui.com/bai-hat/trai-tim-em-cung-biet-dau-bao-anh.0wD8uUkbUMXR.html',
        'md5': '18d6d4f1592af797c6526951355884e2',
        'info_dict': {
            'id': '0wD8uUkbUMXR',
            'ext': 'mp3',
            'title': 'Trái Tim Em Cũng Biết Đau',
            'thumbnail': r're:https?://.*\.jpg$',
            'artist': 'Bảo Anh',
        },
    }]

    def _real_extract(self, url):
        song_id = self._match_id(url)
        webpage = self._download_webpage(url, song_id)

        api_response = self._get_api_response(webpage, song_id)

        return {
            'id': song_id,
            'url': xpath_text(api_response, 'track/location', fatal=True).strip(),
            'title': (xpath_text(api_response, 'track/title').strip()
                      or self._html_search_meta(r'<h1[^>]+itemprop=["\']name["\'][^>]*>([^<]+)', webpage, 'title')),
            'thumbnail': (xpath_text(api_response, 'track/coverimage').strip()
                          or self._html_search_meta('thumbnail', webpage)),
            'artist': (xpath_text(api_response, 'track/creator').strip()
                       or self._html_search_meta('artist', webpage)),
        }


class NhaccuatuiVideoIE(NhaccuatuiBaseIE):
    _VALID_URL = NhaccuatuiBaseIE._VALID_URL_BASE + r'/video' + NhaccuatuiBaseIE._RESOURCE_ID
    _TESTS = [{
        'url': 'https://www.nhaccuatui.com/video/tam-su-tuoi-30-the-first-show-trinh-thang-binh.Rcavsna6iCKkg.html',
        'md5': '01305f7a8d8d71513f589002d0a363a9',
        'info_dict': {
            'id': 'Rcavsna6iCKkg',
            'ext': 'mp4',
            'title': 'Tâm Sự Tuổi 30 (The First Show)',
            'thumbnail': r're:https?://.*\.jpg$',
            'artist': 'Trịnh Thăng Bình',
        },
    }, {
        'url': 'https://www.nhaccuatui.com/video/uoc-mo-cua-me-nct-x-tiktok-rising-stars-soai-nhi.qVMIezjtAXQS2.html',
        'md5': 'bf24d163eaa91c476e30572db3f5c702',
        'info_dict': {
            'id': 'qVMIezjtAXQS2',
            'ext': 'mp4',
            'title': 'Ước Mơ Của Mẹ (NCT x TikTok Rising Stars)',
            'thumbnail': r're:https?://.*\.jpg$',
            'artist': 'Soái Nhi',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        api_response = self._get_api_response(webpage, video_id)

        return {
            'id': video_id,
            'url': xpath_text(api_response, 'track/item/location', fatal=True).strip(),
            'title': (strip_or_none(xpath_text(api_response, 'track/item/title'))
                      or self._html_search_meta(r'<h1[^>]+itemprop=["\']name["\'][^>]*>([^<]+)', webpage, 'title')),
            'thumbnail': (strip_or_none(xpath_text(api_response, 'track/item/image'))
                          or self._html_search_meta('thumbnail', webpage)),
            'artist': (strip_or_none(xpath_text(api_response, 'track/item/singer'))
                       or self._html_search_meta('artist', webpage)),
        }


class NhaccuatuiPlaylistIE(NhaccuatuiBaseIE):
    _VALID_URL = NhaccuatuiBaseIE._VALID_URL_BASE + r'/playlist' + NhaccuatuiBaseIE._RESOURCE_ID
    _TESTS = [{
        'url': 'https://www.nhaccuatui.com/playlist/nhac-viet-hot-thang-052022-va.q8c6RZbW33P6.html',
        'info_dict': {
            'id': 'q8c6RZbW33P6',
            'title': 'Nhạc Việt Hot Tháng 05/2022',
        },
        'playlist_count': 47,
    }, {
        'url': 'https://www.nhaccuatui.com/playlist/trai-tim-em-cung-biet-dau-va.sndGtwrsyqVZ.html?st=5',
        'info_dict': {
            'id': 'sndGtwrsyqVZ',
            'title': 'Trái Tim Em Cũng Biết Đau',
        },
        'playlist_count': 18,
    }]

    def _real_extract(self, url):
        playlist_id = self._match_id(url)
        webpage = self._download_webpage(url, playlist_id)

        return self.playlist_from_matches(
            re.findall(r'<div[^>]class\s*=\s*"item_content"[^>]*>[^<]*<a\s*href="([^"]+)"[^<]+class="name_song"', webpage),
            playlist_id, self._search_regex(r'<div[^>]+class="name_title"[^>]*><h1[^>]*>([^<]+)', webpage, 'title', fatal=False),
            ie=NhaccuatuiTrackIE)
