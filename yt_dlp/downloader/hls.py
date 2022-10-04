import io
import math
import re
import time
import urllib.parse

from . import get_suitable_downloader
from .utils.timeline import HlsTimeline
from .utils.playback import Playback, PlaybackFinish
from .external import FFmpegFD
from .fragment import FragmentFD
from .. import webvtt
from ..dependencies import Cryptodome_AES
from ..utils import HlsMediaManifest, HlsFragment, InitializationFragmentError, bug_reports_message


class HlsBaseFD(FragmentFD):

    def _can_be_downloaded_natively_or_with_ffmpeg(self, manifest):
        allow_unplayable_formats = self.params.get('allow_unplayable_formats')

        is_ffmpeg_available = FFmpegFD.available()
        is_cryptodome_available = Cryptodome_AES is not None
        # https://tools.ietf.org/html/draft-pantos-http-live-streaming-17#section-4.3.2.4
        is_encryption_supported = re.search(r'#EXT-X-KEY:METHOD=(?!NONE|AES-128)', manifest)
        manifest_has_encryption = '#EXT-X-KEY:METHOD=AES-128' in manifest
        manifest_has_drm = re.search('|'.join([
            r'#EXT-X-FAXS-CM:',  # Adobe Flash Access
            r'#EXT-X-(?:SESSION-)?KEY:.*?URI="skd://',  # Apple FairPlay
        ]), manifest)

        if manifest_has_drm and not allow_unplayable_formats:
            self.report_error(
                'This video is DRM protected; Try selecting another format with --format or '
                'add --check-formats to automatically fallback to the next best format')
            return False, False

        if manifest_has_encryption:
            if not is_cryptodome_available and is_ffmpeg_available:
                self.report_warning('The stream has AES-128 encryption and pycryptodomex is not available')
                return True, True

            if not is_cryptodome_available and not is_ffmpeg_available:
                self.report_warning(
                    ('The stream has AES-128 encryption and neither ffmpeg nor pycryptodomex are available; '
                     'Decryption will be performed natively, but will be extremely slow'))
                return True, False

        return True, False

    def _download_manifest(self, info_dict, manifest_url):
        urlh = self.ydl.urlopen(self._prepare_url(info_dict, manifest_url))
        man_url = urlh.geturl()
        manifest = urlh.read().decode('utf-8', 'ignore')

        return urlh, manifest


class HlsFD(HlsBaseFD):
    """
    Download segments in a m3u8 manifest. External downloaders can take over
    the fragment downloads by supporting the 'm3u8_frag_urls' protocol and
    re-defining 'supports_manifest' function
    """

    FD_NAME = 'hlsnative'

    def real_download(self, filename, info_dict):
        man_url = info_dict['url']
        self.to_screen('[%s] Downloading m3u8 manifest' % self.FD_NAME)

        urlh = self.ydl.urlopen(self._prepare_url(info_dict, man_url))
        man_url = urlh.geturl()
        s = urlh.read().decode('utf-8', 'ignore')

        can_be_downloaded_natively, should_try_ffmpeg = self._can_be_downloaded_natively_or_with_ffmpeg(s)
        if not can_be_downloaded_natively:
            if should_try_ffmpeg:
                fd = FFmpegFD(self.ydl, self.params)
                self.report_warning(
                    f'Unsupported features have been detected; extraction will be delegated to {fd.get_basename()}')
                return fd.real_download(filename, info_dict)

            return False

        is_webvtt = info_dict['ext'] == 'vtt'
        if is_webvtt:
            real_downloader = None  # Packing the fragments is not currently supported for external downloader
        else:
            real_downloader = get_suitable_downloader(
                info_dict, self.params, None, protocol='m3u8_frag_urls', to_stdout=(filename == '-'))
        if real_downloader and not real_downloader.supports_manifest(s):
            real_downloader = None
        if real_downloader:
            self.to_screen(f'[{self.FD_NAME}] Fragment downloads will be delegated to {real_downloader.get_basename()}')

        media_manifest = HlsMediaManifest(s, man_url)
        manifest_stats = media_manifest.get_stats()
        ctx = {
            'filename': filename,
            'total_frags': manifest_stats['media_frags'],
            'ad_frags': manifest_stats['ad_frags'],
        }

        if real_downloader:
            self._prepare_external_frag_download(ctx)
        else:
            self._prepare_and_start_frag_download(ctx, info_dict)

        extra_state = ctx.setdefault('extra_state', {})

        extra_query = None
        extra_param_to_segment_url = info_dict.get('extra_param_to_segment_url')
        if extra_param_to_segment_url:
            extra_query = urllib.parse.parse_qs(extra_param_to_segment_url)

        try:
            fragments = media_manifest.get_fragments(info_dict.get('format_index'), ctx['fragment_index'], extra_query)
        except InitializationFragmentError as e:
            self.report_error(e.msg)
            return False

        # We only download the first fragment during the test
        if self.params.get('test', False):
            fragments = [fragments[0] if fragments else None]

        if real_downloader:
            info_dict['fragments'] = fragments
            fd = real_downloader(self.ydl, self.params)
            # TODO: Make progress updates work without hooking twice
            # for ph in self._progress_hooks:
            #     fd.add_progress_hook(ph)
            return fd.real_download(filename, info_dict)

        if is_webvtt:
            def pack_fragment(frag_content, frag_index):
                output = io.StringIO()
                adjust = 0
                overflow = False
                mpegts_last = None
                for block in webvtt.parse_fragment(frag_content):
                    if isinstance(block, webvtt.CueBlock):
                        extra_state['webvtt_mpegts_last'] = mpegts_last
                        if overflow:
                            extra_state['webvtt_mpegts_adjust'] += 1
                            overflow = False
                        block.start += adjust
                        block.end += adjust

                        dedup_window = extra_state.setdefault('webvtt_dedup_window', [])

                        ready = []

                        i = 0
                        is_new = True
                        while i < len(dedup_window):
                            wcue = dedup_window[i]
                            wblock = webvtt.CueBlock.from_json(wcue)
                            i += 1
                            if wblock.hinges(block):
                                wcue['end'] = block.end
                                is_new = False
                                continue
                            if wblock == block:
                                is_new = False
                                continue
                            if wblock.end > block.start:
                                continue
                            ready.append(wblock)
                            i -= 1
                            del dedup_window[i]

                        if is_new:
                            dedup_window.append(block.as_json)
                        for block in ready:
                            block.write_into(output)

                        # we only emit cues once they fall out of the duplicate window
                        continue
                    elif isinstance(block, webvtt.Magic):
                        # take care of MPEG PES timestamp overflow
                        if block.mpegts is None:
                            block.mpegts = 0
                        extra_state.setdefault('webvtt_mpegts_adjust', 0)
                        block.mpegts += extra_state['webvtt_mpegts_adjust'] << 33
                        if block.mpegts < extra_state.get('webvtt_mpegts_last', 0):
                            overflow = True
                            block.mpegts += 1 << 33
                        mpegts_last = block.mpegts

                        if frag_index == 1:
                            extra_state['webvtt_mpegts'] = block.mpegts or 0
                            extra_state['webvtt_local'] = block.local or 0
                            # XXX: block.local = block.mpegts = None ?
                        else:
                            if block.mpegts is not None and block.local is not None:
                                adjust = (
                                    (block.mpegts - extra_state.get('webvtt_mpegts', 0))
                                    - (block.local - extra_state.get('webvtt_local', 0))
                                )
                            continue
                    elif isinstance(block, webvtt.HeaderBlock):
                        if frag_index != 1:
                            # XXX: this should probably be silent as well
                            # or verify that all segments contain the same data
                            self.report_warning(bug_reports_message(
                                'Discarding a %s block found in the middle of the stream; '
                                'if the subtitles display incorrectly,'
                                % (type(block).__name__)))
                            continue
                    block.write_into(output)

                return output.getvalue().encode()

            def fin_fragments():
                dedup_window = extra_state.get('webvtt_dedup_window')
                if not dedup_window:
                    return b''

                output = io.StringIO()
                for cue in dedup_window:
                    webvtt.CueBlock.from_json(cue).write_into(output)

                return output.getvalue().encode()

            self.download_and_append_fragments(
                ctx, fragments, info_dict, pack_func=pack_fragment, finish_func=fin_fragments)
        else:
            return self.download_and_append_fragments(ctx, fragments, info_dict)


class HlsLiveFD(HlsBaseFD):
    FD_NAME = 'hls-live-native'

    def real_download(self, filename, info_dict):
        self.to_screen('[%s] Downloading m3u8 manifest' % self.FD_NAME)
        start_time = time.time()
        ctx = {
            'started': start_time,
            'live': True,
        }

        requested_formats = info_dict.get('requested_formats')
        timelines = []
        if requested_formats:
            for requested_format in requested_formats:
                timelines.append(HlsTimeline[HlsFragment](
                    requested_format['format_id'], requested_format['filepath'], requested_format['url']))
        else:
            timelines.append(HlsTimeline[HlsFragment](info_dict['format_id'], filename, info_dict['url']))

        span = (0, math.inf) if self.params.get('live_from_start') else (start_time, math.inf)
        playback = Playback[HlsFragment, HlsTimeline](timelines, span)

        update_time = None
        is_end_list = False
        try:
            while True:
                processing_start = time.time()

                for timeline in playback.timelines:
                    urlh, manifest = self._download_manifest(info_dict, timeline.manifest_url)

                    media_manifest = HlsMediaManifest(manifest, urlh.geturl())
                    stats = media_manifest.get_stats()
                    fragments = media_manifest.get_fragments()

                    timeline.insert_many(fragments)
                    update_time = stats['target_duration']
                    if stats['is_end_list']:
                        is_end_list = True

                for (timeline, segments) in playback.seek():
                    ctx['filename'] = timeline.filepath
                    self._prepare_and_start_frag_download(ctx, info_dict)
                    self.download_and_append_fragments(ctx, segments, info_dict)

                if is_end_list:
                    break

                sleep_time = update_time - (time.time() - processing_start)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except (KeyboardInterrupt, PlaybackFinish):
            pass

        playback_start = playback.get_start()
        for timeline in timelines:
            timeline_start = playback.get_timeline_start(timeline)

            if requested_formats and not math.isclose(timeline_start, playback_start, abs_tol=0.1, rel_tol=0):
                requested_format = next(
                    fmt for fmt in requested_formats if timeline.timeline_id.startswith(fmt['format_id']))
                requested_format['offset'] = timeline_start - playback_start

            ctx['filename'] = timeline.filepath
            self._prepare_frag_download(ctx)
            self._finish_frag_download(ctx, info_dict)

        return True, True
