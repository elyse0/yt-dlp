import unittest

from yt_dlp.downloader.utils.timeline import Timeline
from yt_dlp.downloader.utils.playback import Playback


class TestTimeline(unittest.TestCase):

    def test_continuous_segments(self):
        timeline = Timeline('test', 'test.mp4')

        timeline.insert_one({
            'start': 0,
            'end': 5,
        })

        timeline.insert_one({
            'start': 5,
            'end': 10,
        })

        self.assertEqual(timeline.get_start(), 0)
        self.assertEqual(timeline.get_end(), 10)
        self.assertEqual(len(timeline.segments), 2)

    def test_overlapping_segments(self):
        timeline = Timeline('test', 'test.mp4')

        timeline.insert_one({
            'start': 0,
            'end': 5,
        })

        timeline.insert_one({
            'start': 4,
            'end': 9,
        })

        self.assertEqual(timeline.get_start(), 0)
        self.assertEqual(timeline.get_end(), 5)
        self.assertEqual(len(timeline.segments), 1)

    def test_non_continuous_segments(self):
        timeline = Timeline('test', 'test.mp4')

        timeline.insert_one({
            'start': 0,
            'end': 5,
        })

        timeline.insert_one({
            'start': 10,
            'end': 15,
        })

        self.assertEqual(timeline.get_start(), 0)
        self.assertEqual(timeline.get_end(), 15)
        self.assertEqual(len(timeline.segments), 2)


class TestPlayback(unittest.TestCase):

    def test_simple_playback(self):
        playback = Playback([
            Timeline('audio', 'audio.mp4'),
            Timeline('video', 'video.mp4')
        ])

        audio_timeline = playback.get_timeline('audio')
        audio_timeline.insert_many([
            {
                'start': 0,
                'end': 5,
            },
            {
                'start': 10,
                'end': 15,
            }
        ])

        video_timeline = playback.get_timeline('video')
        video_timeline.insert_many([
            {
                'start': 0,
                'end': 4,
            },
            {
                'start': 4,
                'end': 8,
            }
        ])

        playback_seek = playback.seek()
        self.assertEqual(playback.get_cursor(), 8)
        # Seeking two timelines
        self.assertEqual(len(playback_seek), 2)

        (timeline, segments) = playback_seek[0]
        self.assertEqual(timeline.timeline_id, 'audio')
        self.assertEqual(len(segments), 1)

        (timeline, segments) = playback_seek[1]
        self.assertEqual(timeline.timeline_id, 'video')
        self.assertEqual(len(segments), 2)

        # Noop
        playback_segments = playback.seek()
        self.assertEqual(playback.get_cursor(), 8)
        self.assertEqual(len(playback_segments), 0)

        video_timeline = playback.get_timeline('video')
        video_timeline.insert_one({
            'start': 8,
            'end': 12,
        })

        playback_segments = playback.seek()
        self.assertEqual(playback.get_cursor(), 12)
        # Seeking two timelines
        self.assertEqual(len(playback_segments), 2)

        (timeline, segments) = playback_seek[0]
        self.assertEqual(timeline.timeline_id, 'audio')
        self.assertEqual(len(segments), 1)

        (timeline, segments) = playback_seek[1]
        self.assertEqual(timeline.timeline_id, 'video')
        self.assertEqual(len(segments), 2)
