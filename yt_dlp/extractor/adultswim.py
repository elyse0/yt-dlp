import json
import re
import time

from .turner import TurnerBaseIE
from .. import InfoExtractor
from ..compat import functools
from ..utils import (
    ExtractorError,
    HlsMediaManifest,
    determine_ext,
    float_or_none,
    int_or_none,
    mimetype2ext,
    parse_age_limit,
    parse_iso8601,
    strip_or_none,
    try_get,
)


class AdultSwimIE(TurnerBaseIE):
    _VALID_URL = r'https?://(?:www\.)?adultswim\.com/videos/(?P<show_path>[^/?#]+)(?:/(?P<episode_path>[^/?#]+))?'

    _TESTS = [{
        'url': 'http://adultswim.com/videos/rick-and-morty/pilot',
        'info_dict': {
            'id': 'rQxZvXQ4ROaSOqq-or2Mow',
            'ext': 'mp4',
            'title': 'Rick and Morty - Pilot',
            'description': 'Rick moves in with his daughter\'s family and establishes himself as a bad influence on his grandson, Morty.',
            'timestamp': 1543294800,
            'upload_date': '20181127',
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
        'expected_warnings': ['Unable to download f4m manifest'],
    }, {
        'url': 'http://www.adultswim.com/videos/tim-and-eric-awesome-show-great-job/dr-steve-brule-for-your-wine/',
        'info_dict': {
            'id': 'sY3cMUR_TbuE4YmdjzbIcQ',
            'ext': 'mp4',
            'title': 'Tim and Eric Awesome Show Great Job! - Dr. Steve Brule, For Your Wine',
            'description': 'Dr. Brule reports live from Wine Country with a special report on wines.  \nWatch Tim and Eric Awesome Show Great Job! episode #20, "Embarrassed" on Adult Swim.',
            'upload_date': '20080124',
            'timestamp': 1201150800,
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
        'skip': '404 Not Found',
    }, {
        'url': 'http://www.adultswim.com/videos/decker/inside-decker-a-new-hero/',
        'info_dict': {
            'id': 'I0LQFQkaSUaFp8PnAWHhoQ',
            'ext': 'mp4',
            'title': 'Decker - Inside Decker: A New Hero',
            'description': 'The guys recap the conclusion of the season. They announce a new hero, take a peek into the Victorville Film Archive and welcome back the talented James Dean.',
            'timestamp': 1469480460,
            'upload_date': '20160725',
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
        'expected_warnings': ['Unable to download f4m manifest'],
    }, {
        'url': 'http://www.adultswim.com/videos/attack-on-titan',
        'info_dict': {
            'id': 'attack-on-titan',
            'title': 'Attack on Titan',
            'description': 'md5:41caa9416906d90711e31dc00cb7db7e',
        },
        'playlist_mincount': 12,
    }, {
        'url': 'http://www.adultswim.com/videos/streams/williams-stream',
        'info_dict': {
            'id': 'd8DEBj7QRfetLsRgFnGEyg',
            'ext': 'mp4',
            'title': r're:^Williams Stream \d{4}-\d{2}-\d{2} \d{2}:\d{2}$',
            'description': 'original programming',
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
        'skip': '404 Not Found',
    }]

    def _real_extract(self, url):
        show_path, episode_path = self._match_valid_url(url).groups()
        display_id = episode_path or show_path
        query = '''query {
  getShowBySlug(slug:"%s") {
    %%s
  }
}''' % show_path
        if episode_path:
            query = query % '''title
    getVideoBySlug(slug:"%s") {
      _id
      auth
      description
      duration
      episodeNumber
      launchDate
      mediaID
      seasonNumber
      poster
      title
      tvRating
    }''' % episode_path
            ['getVideoBySlug']
        else:
            query = query % '''metaDescription
    title
    videos(first:1000,sort:["episode_number"]) {
      edges {
        node {
           _id
           slug
        }
      }
    }'''
        show_data = self._download_json(
            'https://www.adultswim.com/api/search', display_id,
            data=json.dumps({'query': query}).encode(),
            headers={'Content-Type': 'application/json'})['data']['getShowBySlug']
        if episode_path:
            video_data = show_data['getVideoBySlug']
            video_id = video_data['_id']
            episode_title = title = video_data['title']
            series = show_data.get('title')
            if series:
                title = '%s - %s' % (series, title)
            info = {
                'id': video_id,
                'title': title,
                'description': strip_or_none(video_data.get('description')),
                'duration': float_or_none(video_data.get('duration')),
                'formats': [],
                'subtitles': {},
                'age_limit': parse_age_limit(video_data.get('tvRating')),
                'thumbnail': video_data.get('poster'),
                'timestamp': parse_iso8601(video_data.get('launchDate')),
                'series': series,
                'season_number': int_or_none(video_data.get('seasonNumber')),
                'episode': episode_title,
                'episode_number': int_or_none(video_data.get('episodeNumber')),
            }

            auth = video_data.get('auth')
            media_id = video_data.get('mediaID')
            if media_id:
                info.update(self._extract_ngtv_info(media_id, {
                    # CDN_TOKEN_APP_ID from:
                    # https://d2gg02c3xr550i.cloudfront.net/assets/asvp.e9c8bef24322d060ef87.bundle.js
                    'appId': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBJZCI6ImFzLXR2ZS1kZXNrdG9wLXB0enQ2bSIsInByb2R1Y3QiOiJ0dmUiLCJuZXR3b3JrIjoiYXMiLCJwbGF0Zm9ybSI6ImRlc2t0b3AiLCJpYXQiOjE1MzI3MDIyNzl9.BzSCk-WYOZ2GMCIaeVb8zWnzhlgnXuJTCu0jGp_VaZE',
                }, {
                    'url': url,
                    'site_name': 'AdultSwim',
                    'auth_required': auth,
                }))

            if not auth:
                extract_data = self._download_json(
                    'https://www.adultswim.com/api/shows/v1/videos/' + video_id,
                    video_id, query={'fields': 'stream'}, fatal=False) or {}
                assets = try_get(extract_data, lambda x: x['data']['video']['stream']['assets'], list) or []
                for asset in assets:
                    asset_url = asset.get('url')
                    if not asset_url:
                        continue
                    ext = determine_ext(asset_url, mimetype2ext(asset.get('mime_type')))
                    if ext == 'm3u8':
                        info['formats'].extend(self._extract_m3u8_formats(
                            asset_url, video_id, 'mp4', m3u8_id='hls', fatal=False))
                    elif ext == 'f4m':
                        continue
                        # info['formats'].extend(self._extract_f4m_formats(
                        #     asset_url, video_id, f4m_id='hds', fatal=False))
                    elif ext in ('scc', 'ttml', 'vtt'):
                        info['subtitles'].setdefault('en', []).append({
                            'url': asset_url,
                        })
            self._sort_formats(info['formats'])

            return info
        else:
            entries = []
            for edge in show_data.get('videos', {}).get('edges', []):
                video = edge.get('node') or {}
                slug = video.get('slug')
                if not slug:
                    continue
                entries.append(self.url_result(
                    'http://adultswim.com/videos/%s/%s' % (show_path, slug),
                    'AdultSwim', video.get('_id')))
            return self.playlist_result(
                entries, show_path, show_data.get('title'),
                strip_or_none(show_data.get('metaDescription')))


class AdultSwimStreamIE(InfoExtractor):
    IE_NAME = 'adultswim:stream'
    _VALID_URL = r'https?://(?:www\.)?adultswim\.com/streams/(?P<id>[^/?#]+)'

    _TESTS = [{
        'url': 'https://www.adultswim.com/streams/rick-and-morty',
        'info_dict': {
            'id': r're:^rick-and-morty-[1-4]-\d{1,2}$',
            'ext': 'mp4',
            'title': r're:^Rick and Morty S[1-4] EP\d{1,2} .+$',
            'description': 'An infinite loop of Rick and Morty. You\'re welcome. (Marathon available in select regions)',
            'series': 'Rick and Morty',
            # Live episode changes periodically
            'season': str,
            'episode': str,
            'season_number': int,
            'episode_number': int,
            'duration': float,
        },
    }]

    def _get_fragments_and_stats(self, stream_id, manifest_url):
        manifest = self._download_webpage(manifest_url, stream_id)

        media_manifest = HlsMediaManifest(manifest, manifest_url)
        fragments = media_manifest.get_fragments()
        if not fragments:
            raise ExtractorError('Could not find fragments')

        fragment_index_pattern = re.compile(r'/seg-\d+_(?P<fragment_index>\d+)\.ts')

        first_fragment = next(fragment for fragment in fragments if '/live/ad-slate' not in fragment['url'])
        first_fragment_index_str = self._search_regex(fragment_index_pattern, first_fragment['url'], 'fragment_index')

        first_fragment_index = int(first_fragment_index_str)
        if first_fragment_index == 0:
            return fragments

        missing_fragments = []
        for fragment_index in range(first_fragment_index):
            fragment_start = first_fragment['start'] - (first_fragment['duration'] * (first_fragment_index - fragment_index))
            missing_fragments.append({
                **first_fragment,
                'frag_index': first_fragment['frag_index'] - (first_fragment_index - fragment_index),
                'media_sequence': first_fragment['media_sequence'] - (first_fragment_index - fragment_index),
                'url': first_fragment['url'].replace(
                    first_fragment_index_str, f'{fragment_index:0{len(first_fragment_index_str)}}'),
                'start': fragment_start,
                'end': fragment_start + first_fragment['duration'],
            })

        all_fragments = missing_fragments + fragments

        return all_fragments, media_manifest.get_stats()

    def _real_extract(self, url):
        stream_id = self._match_id(url)
        webpage = self._download_webpage(url, stream_id)

        nextjs_data = self._search_nextjs_data(webpage, stream_id)['props']['__REDUX_STATE__']
        stream_info = next(stream for stream in nextjs_data['streams'] if stream['id'] == stream_id)

        start_time = time.time()
        episodes = []
        for episode in nextjs_data['marathon'][stream_info['vod_to_live_id']]:
            if episode['startTime'] / 1000 + episode['duration'] < start_time:
                continue
            episodes.append(episode)

        if not episodes:
            raise ExtractorError('No episodes found')

        formats, subtitles = self._extract_m3u8_formats_and_subtitles(
            f'https://adultswim-vodlive.cdn.turner.com/live/{stream_id}/stream_de.m3u8?hdnts=', stream_id)

        for fmt in formats:
            fmt['protocol'] = 'm3u8_native_generator'
            fmt['fragments_and_stats'] = functools.partial(self._get_fragments_and_stats, stream_id)

        self._sort_formats(formats)
        return {
            'id': stream_id,
            'title': stream_info.get('title'),
            'description': stream_info.get('description'),
            'formats': formats,
            'subtitles': subtitles,
            'is_live': True,
            'live_start': time.time(),
            'live_end': time.time() + 5 * 60
        }
