from __future__ import annotations

import http.client
import urllib.error
import urllib.parse
import binascii
import re
from io import BufferedWriter
from typing import TypedDict, Dict
from typing_extensions import NotRequired

from . import get_suitable_downloader
from yt_dlp.downloader.fragment import FragmentFD
from .common import FileDownloader
from .http import HttpFD
from ..utils import (
    DownloadError,
    parse_m3u8_attributes,
    update_url_query,
)


class FragmentByteRange(TypedDict):
    start: int
    end: int


class Fragment(TypedDict):
    index: int
    url: str
    byte_range: NotRequired[FragmentByteRange]


class Ctx(TypedDict):
    id: str
    dl: HttpFD
    fragment_index: int
    fragment_count: int
    dest_stream: BufferedWriter
    tmpfilename: str
    last_error: urllib.error.HTTPError | http.client.IncompleteRead | None


class FragmentLiveConfig(TypedDict):
    max_retries: int
    http_headers: Dict[str, str] | None


class HlsLiveDl(FragmentFD):
    ctx: Ctx
    config: FragmentLiveConfig

    def _download_fragment(self, fragment: Fragment, headers: Dict[str, str]):
        fragment_filename = f'{self.ctx["tmpfilename"]}-Frag{self.ctx["fragment_index"]}'
        fragment_info_dict = {
            'url': fragment['url'],
            'http_headers': headers.update(self.config['http_headers']),
            'ctx_id': self.ctx.get('id'),
        }
        success, _ = self.ctx['dl'].download(fragment_filename, fragment_info_dict)
        return True if success else False

    def download_fragment(self, fragment: Fragment, ctx: Ctx):
        ctx['fragment_index'] = fragment['index']
        ctx['last_error'] = None

        headers = self.config['http_headers'].copy()

        byte_range = fragment.get('byte_range')
        if byte_range:
            headers['Range'] = f'bytes={byte_range["start"]}-{byte_range["end"] - 1}'

        # Never skip the first fragment
        fatal, count = is_fatal(fragment['index'] or (fragment['index'] - 1)), 0
        while count <= self.config['max_retries']:
            try:
                ctx['fragment_count'] = fragment['index']
                if self._download_fragment(ctx, fragment['url'], info_dict, headers):
                    break
                return
            except (urllib.error.HTTPError, http.client.IncompleteRead) as err:
                # Unavailable (possibly temporary) fragments may be served.
                # First we try to retry then either skip or abort.
                # See https://github.com/ytdl-org/youtube-dl/issues/10165,
                # https://github.com/ytdl-org/youtube-dl/issues/10448).
                count += 1
                ctx['last_error'] = err
                self.report_retry_fragment(err, fragment_index, count, fragment_retries)
            except DownloadError:
                # Don't retry fragment if error occurred during HTTP downloading
                # itself since it has own retry settings
                if not fatal:
                    break
                raise

        if count > self.config['max_retries'] and fatal:
            ctx['dest_stream'].close()
            self.report_error(f'Giving up after {count} fragment retries')

    def _get_fragments(self, manifest_url: str, filename: str, info_dict: Dict[str, str]):
        def is_ad_fragment_start(s):
            return (s.startswith('#ANVATO-SEGMENT-INFO') and 'type=ad' in s
                    or s.startswith('#UPLYNK-SEGMENT') and s.endswith(',ad'))

        def is_ad_fragment_end(s):
            return (s.startswith('#ANVATO-SEGMENT-INFO') and 'type=master' in s
                    or s.startswith('#UPLYNK-SEGMENT') and s.endswith(',segment'))

        self.to_screen('[%s] Downloading m3u8 manifest' % self.FD_NAME)

        urlh = self.ydl.urlopen(self._prepare_url(info_dict, manifest_url))
        man_url = urlh.geturl()
        manifest = urlh.read().decode('utf-8', 'ignore')

        fragments = []

        media_frags = 0
        ad_frags = 0
        ad_frag_next = False
        for line in manifest.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if is_ad_fragment_start(line):
                    ad_frag_next = True
                elif is_ad_fragment_end(line):
                    ad_frag_next = False
                continue
            if ad_frag_next:
                ad_frags += 1
                continue
            media_frags += 1

        ctx = {
            'filename': filename,
            'total_frags': media_frags,
            'ad_frags': ad_frags,
        }

        is_webvtt = info_dict['ext'] == 'vtt'
        if is_webvtt:
            real_downloader = None  # Packing the fragments is not currently supported for external downloader
        else:
            real_downloader = get_suitable_downloader(
                info_dict, self.params, None, protocol='m3u8_frag_urls', to_stdout=(filename == '-'))

        if real_downloader and not real_downloader.supports_manifest(manifest):
            real_downloader = None
        if real_downloader:
            self.to_screen(f'[{self.FD_NAME}] Fragment downloads will be delegated to {real_downloader.get_basename()}')

        if real_downloader:
            self._prepare_external_frag_download(ctx)
        else:
            self._prepare_and_start_frag_download(ctx, info_dict)

        extra_state = ctx.setdefault('extra_state', {})

        format_index = info_dict.get('format_index')
        extra_query = None
        extra_param_to_segment_url = info_dict.get('extra_param_to_segment_url')
        if extra_param_to_segment_url:
            extra_query = urllib.parse.parse_qs(extra_param_to_segment_url)
        i = 0
        media_sequence = 0
        decrypt_info = {'METHOD': 'NONE'}
        byte_range = {}
        discontinuity_count = 0
        frag_index = 0
        ad_frag_next = False
        for line in manifest.splitlines():
            line = line.strip()
            if line:
                if not line.startswith('#'):
                    if format_index and discontinuity_count != format_index:
                        continue
                    if ad_frag_next:
                        continue
                    frag_index += 1
                    if frag_index <= ctx['fragment_index']:
                        continue
                    frag_url = (
                        line
                        if re.match(r'^https?://', line)
                        else urllib.parse.urljoin(man_url, line))
                    if extra_query:
                        frag_url = update_url_query(frag_url, extra_query)

                    fragments.append({
                        'frag_index': frag_index,
                        'url': frag_url,
                        'decrypt_info': decrypt_info,
                        'byte_range': byte_range,
                        'media_sequence': media_sequence,
                    })
                    media_sequence += 1

                elif line.startswith('#EXT-X-MAP'):
                    if format_index and discontinuity_count != format_index:
                        continue
                    if frag_index > 0:
                        self.report_error(
                            'Initialization fragment found after media fragments, unable to download')
                        return False
                    frag_index += 1
                    map_info = parse_m3u8_attributes(line[11:])
                    frag_url = (
                        map_info.get('URI')
                        if re.match(r'^https?://', map_info.get('URI'))
                        else urllib.parse.urljoin(man_url, map_info.get('URI')))
                    if extra_query:
                        frag_url = update_url_query(frag_url, extra_query)

                    if map_info.get('BYTERANGE'):
                        splitted_byte_range = map_info.get('BYTERANGE').split('@')
                        sub_range_start = int(splitted_byte_range[1]) if len(splitted_byte_range) == 2 else byte_range[
                            'end']
                        byte_range = {
                            'start': sub_range_start,
                            'end': sub_range_start + int(splitted_byte_range[0]),
                        }

                    fragments.append({
                        'frag_index': frag_index,
                        'url': frag_url,
                        'decrypt_info': decrypt_info,
                        'byte_range': byte_range,
                        'media_sequence': media_sequence
                    })
                    media_sequence += 1

                elif line.startswith('#EXT-X-KEY'):
                    decrypt_url = decrypt_info.get('URI')
                    decrypt_info = parse_m3u8_attributes(line[11:])
                    if decrypt_info['METHOD'] == 'AES-128':
                        if 'IV' in decrypt_info:
                            decrypt_info['IV'] = binascii.unhexlify(decrypt_info['IV'][2:].zfill(32))
                        if not re.match(r'^https?://', decrypt_info['URI']):
                            decrypt_info['URI'] = urllib.parse.urljoin(
                                man_url, decrypt_info['URI'])
                        if extra_query:
                            decrypt_info['URI'] = update_url_query(decrypt_info['URI'], extra_query)
                        if decrypt_url != decrypt_info['URI']:
                            decrypt_info['KEY'] = None

                elif line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                    media_sequence = int(line[22:])
                elif line.startswith('#EXT-X-BYTERANGE'):
                    splitted_byte_range = line[17:].split('@')
                    sub_range_start = int(splitted_byte_range[1]) if len(splitted_byte_range) == 2 else byte_range[
                        'end']
                    byte_range = {
                        'start': sub_range_start,
                        'end': sub_range_start + int(splitted_byte_range[0]),
                    }
                elif is_ad_fragment_start(line):
                    ad_frag_next = True
                elif is_ad_fragment_end(line):
                    ad_frag_next = False
                elif line.startswith('#EXT-X-DISCONTINUITY'):
                    discontinuity_count += 1

                i += 1

    def real_download(self, filename, info_dict):
        pass
