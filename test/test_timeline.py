import unittest

from yt_dlp.timeline import (
    Playback,
    Timeline
)


class TestTimeline(unittest.TestCase):

    def test_simple_timeline(self):
        timeline = Timeline('test', 'test.mp4')

        timeline.insert_one({
            'start': 0,
            'end': 5,
            'data': {
                'url': 'https://some-cdn.com/frag-0',
            },
        })

        timeline.insert_one({
            'start': 5,
            'end': 10,
            'data': {
                'url': 'https://some-cdn.com/frag-1',
            },
        })

        self.assertEqual(timeline.get_start(), 0)
        self.assertEqual(timeline.get_end(), 10)
        self.assertEqual(len(timeline.segments), 2)

    def test_simple_filled_timeline(self):
        timeline = Timeline('test', 'test.mp4')

        timeline.insert_one({
            'start': 0,
            'end': 5,
            'data': {
                'url': 'https://some-cdn.com/frag-0',
            },
        })

        timeline.insert_one({
            'start': 10,
            'end': 15,
            'data': {
                'url': 'https://some-cdn.com/frag-1',
            },
        })

        self.assertEqual(timeline.get_start(), 0)
        self.assertEqual(timeline.get_end(), 15)
        self.assertEqual(len(timeline.segments), 3)
        self.assertEqual(sum(segment['filling'] for segment in timeline.segments), 1)


class TestPlayback(unittest.TestCase):

    def test_simple_playback(self):
        playback = Playback([Timeline('0', 'track-0.mp4'), Timeline('1', 'track-1.mp4')])

        audio_timeline = playback.get_track('0')
        audio_timeline.insert_many([
            {
                'start': 0,
                'end': 5,
                'data': {
                    'url': 'https://some-cdn.com/frag-0',
                },
            },
            {
                'start': 10,
                'end': 15,
                'data': {
                    'url': 'https://some-cdn.com/frag-1',
                },
            }
        ])

        video_timeline = playback.get_track('1')
        video_timeline.insert_many([
            {
                'start': 0,
                'end': 4,
                'data': {
                    'url': 'https://some-cdn.com/frag-0',
                },
            },
            {
                'start': 4,
                'end': 8,
                'data': {
                    'url': 'https://some-cdn.com/frag-1',
                },
            }
        ])

        playback_segments = playback.seek()
        self.assertEqual(playback.cursor, 8)
        self.assertEqual(len(playback_segments), 4)

        # Noop
        playback_segments = playback.seek()
        self.assertEqual(playback.cursor, 8)
        self.assertEqual(len(playback_segments), 0)

        video_timeline = playback.get_track('1')
        video_timeline.insert_one({
            'start': 8,
            'end': 12,
            'data': {
                'url': 'https://some-cdn.com/frag-2',
            },
        })

        playback_segments = playback.seek()
        self.assertEqual(playback.cursor, 12)
        self.assertEqual(len(playback_segments), 2)
