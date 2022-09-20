import math
from itertools import chain
from typing import Any, List, Optional, TypedDict


class Segment(TypedDict):
    start: float
    end: float
    data: Any


class TimelineSegment(Segment):
    filling: bool

class TimelineSignatureSegment(TimelineSegment):
    track_id: str
    filename: str

class Timeline:
    def __init__(self, track_id: str, filename: str):
        self.track_id = track_id
        self.filename = filename
        self.segments: List[TimelineSegment] = []

    def get_signature_segments(self) -> List[TimelineSignatureSegment]:
        signature_segments = []
        for segment in self.segments:
            signature_segments.append({
                'track_id': self.track_id,
                'filename': self.filename,
                'start': segment['start'],
                'end': segment['end'],
                'data': segment['data'],
                'filling': segment['filling'],
            })

        return signature_segments

    def get_start(self) -> Optional[float]:
        if not len(self.segments):
            return None

        return self.segments[0]['start']

    def get_end(self) -> Optional[float]:
        if not len(self.segments):
            return None

        return self.segments[-1]['end']

    def get_at_start(self, start) -> Optional[Segment]:
        return next(segment for segment in self.segments if segment['start'] == start)

    def get_segment_ends(self) -> List[float]:
        return list(map(lambda segment: segment['end'], self.segments))

    def get_segments_after(self, cursor: float):
        return list(filter(lambda segment: segment['start'] >= cursor, self.segments))

    def _insert_timeline_segment(self, segment: Segment, filling: bool):
        timeline_segment: TimelineSegment = {
            'start': segment['start'],
            'end': segment['end'],
            'data': segment['data'],
            'filling': filling
        }
        self.segments.append(timeline_segment)

    def insert_one(self, new_segment: Segment) -> None:
        if not len(self.segments):
            self._insert_timeline_segment(new_segment, False)
            return

        last_segment = self.segments[-1]
        if last_segment['end'] > new_segment['start']:
            return

        if math.isclose(last_segment['end'], new_segment['start'], abs_tol=0.01):
            self._insert_timeline_segment(new_segment, False)
            return

        self._insert_timeline_segment({
            'start': last_segment['end'],
            'end': new_segment['start'],
            'data': None,
        }, True)
        self._insert_timeline_segment(new_segment, False)

    def insert_many(self, segments: List[Segment]):
        for segment in segments:
            self.insert_one(segment)


class Playback:

    def __init__(self, tracks: List[Timeline]):
        self.cursor = 0
        self.tracks = tracks

    def get_track(self, track_id) -> Optional[Timeline]:
        return next(track for track in self.tracks if track.track_id == track_id)

    def _get_next_cursor(self):
        def get_values_bigger_or_equal_than(values: List[float], target: float):
            return list(filter(lambda value: value >= target, values))

        tracks_ends = list(map(lambda track: track.get_segment_ends(), self.tracks))

        available_starts = list(
            map(lambda track_starts: get_values_bigger_or_equal_than(track_starts, self.cursor), tracks_ends))

        return min(map(lambda values: max(values), available_starts))

    def seek(self) -> List[TimelineSignatureSegment]:
        next_cursor = self._get_next_cursor()

        segments = list(chain.from_iterable(map(lambda track: track.get_signature_segments(), self.tracks)))
        filtered_segments = list(filter(lambda segment: self.cursor <= segment['start'] < next_cursor, segments))

        self.cursor = next_cursor
        return filtered_segments
