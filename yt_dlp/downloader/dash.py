import collections
import math
import re
import time
import urllib.parse

from . import get_suitable_downloader
from .fragment import FragmentFD
from ..utils import (
    ExtractorError,
    float_or_none,
    int_or_none,
    mimetype2ext,
    parse_codecs,
    parse_duration,
    try_call,
    try_get,
    urljoin,
)


class MpdManifest:

    @staticmethod
    def parse_formats_and_subtitles(mpd_doc, mpd_id=None, mpd_base_url='', mpd_url=None, dynamic_mpd=True):
        """
            Parse formats from MPD manifest.
            References:
            1. MPEG-DASH Standard, ISO/IEC 23009-1:2014(E),
               http://standards.iso.org/ittf/PubliclyAvailableStandards/c065274_ISO_IEC_23009-1_2014.zip
            2. https://en.wikipedia.org/wiki/Dynamic_Adaptive_Streaming_over_HTTP
        """
        if not dynamic_mpd:
            if mpd_doc.get('type') == 'dynamic':
                return [], {}

        namespace = re.search(r'(?i)^{([^}]+)?}MPD$', mpd_doc.tag).group(1)

        # Copied from extractor/common.py
        def _xpath_ns(path, namespace=None):
            if not namespace:
                return path
            out = []
            for c in path.split('/'):
                if not c or c == '.':
                    out.append(c)
                else:
                    out.append('{%s}%s' % (namespace, c))
            return '/'.join(out)

        def _add_ns(path):
            return _xpath_ns(path, namespace)

        def is_drm_protected(element):
            return element.find(_add_ns('ContentProtection')) is not None

        def extract_multisegment_info(element, ms_parent_info):
            ms_info = ms_parent_info.copy()

            # As per [1, 5.3.9.2.2] SegmentList and SegmentTemplate share some
            # common attributes and elements.  We will only extract relevant
            # for us.
            def extract_common(source):
                segment_timeline = source.find(_add_ns('SegmentTimeline'))
                if segment_timeline is not None:
                    s_e = segment_timeline.findall(_add_ns('S'))
                    if s_e:
                        ms_info['total_number'] = 0
                        ms_info['s'] = []
                        for s in s_e:
                            r = int(s.get('r', 0))
                            ms_info['total_number'] += 1 + r
                            ms_info['s'].append({
                                't': int_or_none(s.get('t')),
                                # @d is mandatory (see [1, 5.3.9.6.2, Table 17, page 60])
                                'd': int(s.attrib['d']),
                                'r': r,
                            })
                start_number = source.get('startNumber')
                if start_number:
                    ms_info['start_number'] = int(start_number)
                timescale = source.get('timescale')
                if timescale:
                    ms_info['timescale'] = int(timescale)
                segment_duration = source.get('duration')
                if segment_duration:
                    ms_info['segment_duration'] = float(segment_duration)

            def extract_Initialization(source):
                initialization = source.find(_add_ns('Initialization'))
                if initialization is not None:
                    ms_info['initialization_url'] = initialization.attrib['sourceURL']

            segment_list = element.find(_add_ns('SegmentList'))
            if segment_list is not None:
                extract_common(segment_list)
                extract_Initialization(segment_list)
                segment_urls_e = segment_list.findall(_add_ns('SegmentURL'))
                if segment_urls_e:
                    ms_info['segment_urls'] = [segment.attrib['media'] for segment in segment_urls_e]
            else:
                segment_template = element.find(_add_ns('SegmentTemplate'))
                if segment_template is not None:
                    extract_common(segment_template)
                    media = segment_template.get('media')
                    if media:
                        ms_info['media'] = media
                    initialization = segment_template.get('initialization')
                    if initialization:
                        ms_info['initialization'] = initialization
                    else:
                        extract_Initialization(segment_template)
            return ms_info

        mpd_duration = parse_duration(mpd_doc.get('mediaPresentationDuration'))
        formats, subtitles = [], {}
        stream_numbers = collections.defaultdict(int)
        for period in mpd_doc.findall(_add_ns('Period')):
            period_duration = parse_duration(period.get('duration')) or mpd_duration
            period_ms_info = extract_multisegment_info(period, {
                'start_number': 1,
                'timescale': 1,
            })
            for adaptation_set in period.findall(_add_ns('AdaptationSet')):
                adaption_set_ms_info = extract_multisegment_info(adaptation_set, period_ms_info)
                for representation in adaptation_set.findall(_add_ns('Representation')):
                    representation_attrib = adaptation_set.attrib.copy()
                    representation_attrib.update(representation.attrib)
                    # According to [1, 5.3.7.2, Table 9, page 41], @mimeType is mandatory
                    mime_type = representation_attrib['mimeType']
                    content_type = representation_attrib.get('contentType', mime_type.split('/')[0])

                    codec_str = representation_attrib.get('codecs', '')
                    # Some kind of binary subtitle found in some youtube livestreams
                    if mime_type == 'application/x-rawcc':
                        codecs = {'scodec': codec_str}
                    else:
                        codecs = parse_codecs(codec_str)
                    if content_type not in ('video', 'audio', 'text'):
                        if mime_type == 'image/jpeg':
                            content_type = mime_type
                        elif codecs.get('vcodec', 'none') != 'none':
                            content_type = 'video'
                        elif codecs.get('acodec', 'none') != 'none':
                            content_type = 'audio'
                        elif codecs.get('scodec', 'none') != 'none':
                            content_type = 'text'
                        elif mimetype2ext(mime_type) in ('tt', 'dfxp', 'ttml', 'xml', 'json'):
                            content_type = 'text'
                        else:
                            # self.report_warning('Unknown MIME type %s in DASH manifest' % mime_type)
                            # continue
                            raise ExtractorError('Unknown MIME type %s in DASH manifest' % mime_type)

                    base_url = ''
                    for element in (representation, adaptation_set, period, mpd_doc):
                        base_url_e = element.find(_add_ns('BaseURL'))
                        if try_call(lambda: base_url_e.text) is not None:
                            base_url = base_url_e.text + base_url
                            if re.match(r'^https?://', base_url):
                                break
                    if mpd_base_url and base_url.startswith('/'):
                        base_url = urllib.parse.urljoin(mpd_base_url, base_url)
                    elif mpd_base_url and not re.match(r'^https?://', base_url):
                        if not mpd_base_url.endswith('/'):
                            mpd_base_url += '/'
                        base_url = mpd_base_url + base_url
                    representation_id = representation_attrib.get('id')
                    lang = representation_attrib.get('lang')
                    url_el = representation.find(_add_ns('BaseURL'))
                    filesize = int_or_none(url_el.attrib.get(
                        '{http://youtube.com/yt/2012/10/10}contentLength') if url_el is not None else None)
                    bandwidth = int_or_none(representation_attrib.get('bandwidth'))
                    if representation_id is not None:
                        format_id = representation_id
                    else:
                        format_id = content_type
                    if mpd_id:
                        format_id = mpd_id + '-' + format_id
                    if content_type in ('video', 'audio'):
                        f = {
                            'format_id': format_id,
                            'manifest_url': mpd_url,
                            'ext': mimetype2ext(mime_type),
                            'width': int_or_none(representation_attrib.get('width')),
                            'height': int_or_none(representation_attrib.get('height')),
                            'tbr': float_or_none(bandwidth, 1000),
                            'asr': int_or_none(representation_attrib.get('audioSamplingRate')),
                            'fps': int_or_none(representation_attrib.get('frameRate')),
                            'language': lang if lang not in ('mul', 'und', 'zxx', 'mis') else None,
                            'format_note': 'DASH %s' % content_type,
                            'filesize': filesize,
                            'container': mimetype2ext(mime_type) + '_dash',
                            **codecs
                        }
                    elif content_type == 'text':
                        f = {
                            'ext': mimetype2ext(mime_type),
                            'manifest_url': mpd_url,
                            'filesize': filesize,
                        }
                    elif content_type == 'image/jpeg':
                        # See test case in VikiIE
                        # https://www.viki.com/videos/1175236v-choosing-spouse-by-lottery-episode-1
                        f = {
                            'format_id': format_id,
                            'ext': 'mhtml',
                            'manifest_url': mpd_url,
                            'format_note': 'DASH storyboards (jpeg)',
                            'acodec': 'none',
                            'vcodec': 'none',
                        }
                    if is_drm_protected(adaptation_set) or is_drm_protected(representation):
                        f['has_drm'] = True
                    representation_ms_info = extract_multisegment_info(representation, adaption_set_ms_info)

                    def prepare_template(template_name, identifiers):
                        tmpl = representation_ms_info[template_name]
                        if representation_id is not None:
                            tmpl = tmpl.replace('$RepresentationID$', representation_id)
                        # First of, % characters outside $...$ templates
                        # must be escaped by doubling for proper processing
                        # by % operator string formatting used further (see
                        # https://github.com/ytdl-org/youtube-dl/issues/16867).
                        t = ''
                        in_template = False
                        for c in tmpl:
                            t += c
                            if c == '$':
                                in_template = not in_template
                            elif c == '%' and not in_template:
                                t += c
                        # Next, $...$ templates are translated to their
                        # %(...) counterparts to be used with % operator
                        t = re.sub(r'\$(%s)\$' % '|'.join(identifiers), r'%(\1)d', t)
                        t = re.sub(r'\$(%s)%%([^$]+)\$' % '|'.join(identifiers), r'%(\1)\2', t)
                        t.replace('$$', '$')
                        return t

                    # @initialization is a regular template like @media one
                    # so it should be handled just the same way (see
                    # https://github.com/ytdl-org/youtube-dl/issues/11605)
                    if 'initialization' in representation_ms_info:
                        initialization_template = prepare_template(
                            'initialization',
                            # As per [1, 5.3.9.4.2, Table 15, page 54] $Number$ and
                            # $Time$ shall not be included for @initialization thus
                            # only $Bandwidth$ remains
                            ('Bandwidth',))
                        representation_ms_info['initialization_url'] = initialization_template % {
                            'Bandwidth': bandwidth,
                        }

                    def location_key(location):
                        return 'url' if re.match(r'^https?://', location) else 'path'

                    if 'segment_urls' not in representation_ms_info and 'media' in representation_ms_info:

                        media_template = prepare_template('media', ('Number', 'Bandwidth', 'Time'))
                        media_location_key = location_key(media_template)

                        # As per [1, 5.3.9.4.4, Table 16, page 55] $Number$ and $Time$
                        # can't be used at the same time
                        if '%(Number' in media_template and 's' not in representation_ms_info:
                            segment_duration = None
                            if 'total_number' not in representation_ms_info and 'segment_duration' in representation_ms_info:
                                segment_duration = float_or_none(representation_ms_info['segment_duration'],
                                                                 representation_ms_info['timescale'])
                                representation_ms_info['total_number'] = int(math.ceil(
                                    float_or_none(period_duration, segment_duration, default=0)))
                            representation_ms_info['fragments'] = [{
                                media_location_key: media_template % {
                                    'Number': segment_number,
                                    'Bandwidth': bandwidth,
                                },
                                'duration': segment_duration,
                            } for segment_number in range(
                                representation_ms_info['start_number'],
                                representation_ms_info['total_number'] + representation_ms_info['start_number'])]
                        else:
                            # $Number*$ or $Time$ in media template with S list available
                            # Example $Number*$: http://www.svtplay.se/klipp/9023742/stopptid-om-bjorn-borg
                            # Example $Time$: https://play.arkena.com/embed/avp/v2/player/media/b41dda37-d8e7-4d3f-b1b5-9a9db578bdfe/1/129411
                            representation_ms_info['fragments'] = []
                            segment_time = 0
                            segment_d = None
                            segment_number = representation_ms_info['start_number']

                            def add_segment_url():
                                segment_url = media_template % {
                                    'Time': segment_time,
                                    'Bandwidth': bandwidth,
                                    'Number': segment_number,
                                }
                                duration = float_or_none(segment_d, representation_ms_info['timescale'])
                                start = float_or_none(segment_time, representation_ms_info['timescale'])
                                representation_ms_info['fragments'].append({
                                    media_location_key: segment_url,
                                    'duration': duration,
                                    'start': start,
                                    'end': start + duration,
                                })

                            for num, s in enumerate(representation_ms_info['s']):
                                segment_t = s.get('t')
                                if segment_t:
                                    segment_time = segment_t
                                segment_d = s['d']
                                add_segment_url()
                                segment_number += 1
                                for r in range(s.get('r', 0)):
                                    segment_time += segment_d
                                    add_segment_url()
                                    segment_number += 1
                                segment_time += segment_d
                    elif 'segment_urls' in representation_ms_info and 's' in representation_ms_info:
                        # No media template,
                        # e.g. https://www.youtube.com/watch?v=iXZV5uAYMJI
                        # or any YouTube dashsegments video
                        fragments = []
                        segment_index = 0
                        timescale = representation_ms_info['timescale']
                        for s in representation_ms_info['s']:
                            duration = float_or_none(s['d'], timescale)
                            for r in range(s.get('r', 0) + 1):
                                segment_uri = representation_ms_info['segment_urls'][segment_index]
                                fragments.append({
                                    location_key(segment_uri): segment_uri,
                                    'duration': duration,
                                })
                                segment_index += 1
                        representation_ms_info['fragments'] = fragments
                    elif 'segment_urls' in representation_ms_info:
                        # Segment URLs with no SegmentTimeline
                        # E.g. https://www.seznam.cz/zpravy/clanek/cesko-zasahne-vitr-o-sile-vichrice-muze-byt-i-zivotu-nebezpecny-39091
                        # https://github.com/ytdl-org/youtube-dl/pull/14844
                        fragments = []
                        segment_duration = float_or_none(
                            representation_ms_info['segment_duration'],
                            representation_ms_info[
                                'timescale']) if 'segment_duration' in representation_ms_info else None
                        for segment_url in representation_ms_info['segment_urls']:
                            fragment = {
                                location_key(segment_url): segment_url,
                            }
                            if segment_duration:
                                fragment['duration'] = segment_duration
                            fragments.append(fragment)
                        representation_ms_info['fragments'] = fragments
                    # If there is a fragments key available then we correctly recognized fragmented media.
                    # Otherwise we will assume unfragmented media with direct access. Technically, such
                    # assumption is not necessarily correct since we may simply have no support for
                    # some forms of fragmented media renditions yet, but for now we'll use this fallback.
                    if 'fragments' in representation_ms_info:
                        f.update({
                            # NB: mpd_url may be empty when MPD manifest is parsed from a string
                            'url': mpd_url or base_url,
                            'fragment_base_url': base_url,
                            'fragments': [],
                            'protocol': 'http_dash_segments' if mime_type != 'image/jpeg' else 'mhtml',
                        })
                        if 'initialization_url' in representation_ms_info:
                            initialization_url = representation_ms_info['initialization_url']
                            if not f.get('url'):
                                f['url'] = initialization_url
                            f['fragments'].append({location_key(initialization_url): initialization_url})
                        f['fragments'].extend(representation_ms_info['fragments'])
                        if not period_duration:
                            period_duration = try_get(
                                representation_ms_info,
                                lambda r: sum(frag['duration'] for frag in r['fragments']), float)
                    else:
                        # Assuming direct URL to unfragmented media.
                        f['url'] = base_url
                    if content_type in ('video', 'audio', 'image/jpeg'):
                        f['manifest_stream_number'] = stream_numbers[f['url']]
                        stream_numbers[f['url']] += 1
                        formats.append(f)
                    elif content_type == 'text':
                        subtitles.setdefault(lang or 'und', []).append(f)

        return formats, subtitles


class DashSegmentsFD(FragmentFD):
    """
    Download segments in a DASH manifest. External downloaders can take over
    the fragment downloads by supporting the 'dash_frag_urls' protocol
    """

    FD_NAME = 'dashsegments'

    def real_download(self, filename, info_dict):
        if info_dict.get('is_live') and set(info_dict['protocol'].split('+')) != {'http_dash_segments_generator'}:
            self.report_error('Live DASH videos are not supported')

        real_start = time.time()
        real_downloader = get_suitable_downloader(
            info_dict, self.params, None, protocol='dash_frag_urls', to_stdout=(filename == '-'))

        requested_formats = [{**info_dict, **fmt} for fmt in info_dict.get('requested_formats', [])]
        args = []
        for fmt in requested_formats or [info_dict]:
            try:
                fragment_count = 1 if self.params.get('test') else len(fmt['fragments'])
            except TypeError:
                fragment_count = None
            ctx = {
                'filename': fmt.get('filepath') or filename,
                'live': 'is_from_start' if fmt.get('is_from_start') else fmt.get('is_live'),
                'total_frags': fragment_count,
            }

            if real_downloader:
                self._prepare_external_frag_download(ctx)
            else:
                self._prepare_and_start_frag_download(ctx, fmt)
            ctx['start'] = real_start

            fragments_to_download = self._get_fragments(fmt, ctx)

            if real_downloader:
                self.to_screen(
                    f'[{self.FD_NAME}] Fragment downloads will be delegated to {real_downloader.get_basename()}')
                info_dict['fragments'] = list(fragments_to_download)
                fd = real_downloader(self.ydl, self.params)
                return fd.real_download(filename, info_dict)

            args.append([ctx, fragments_to_download, fmt])

        return self.download_and_append_fragments_multiple(*args, is_fatal=lambda idx: idx == 0)

    def _resolve_fragments(self, fragments, ctx):
        fragments = fragments(ctx) if callable(fragments) else fragments
        return [next(iter(fragments))] if self.params.get('test') else fragments

    def _get_fragments(self, fmt, ctx):
        fragment_base_url = fmt.get('fragment_base_url')
        fragments = self._resolve_fragments(fmt['fragments'], ctx)

        frag_index = 0
        for i, fragment in enumerate(fragments):
            frag_index += 1
            if frag_index <= ctx['fragment_index']:
                continue
            fragment_url = fragment.get('url')
            if not fragment_url:
                assert fragment_base_url
                fragment_url = urljoin(fragment_base_url, fragment['path'])

            yield {
                'frag_index': frag_index,
                'fragment_count': fragment.get('fragment_count'),
                'index': i,
                'url': fragment_url,
            }
