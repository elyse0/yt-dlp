from typing import Generic, List, Optional, Tuple, TypeVar

from .timeline import Timeline, GenericFragment
from ...utils import YoutubeDLError

GenericTimeline = TypeVar('GenericTimeline', bound=Timeline)


class PlaybackFinish(YoutubeDLError):
    def __init__(self):
        super().__init__('Playback finish')


class Playback(Generic[GenericFragment, GenericTimeline]):

    def __init__(self, timelines: List[GenericTimeline], span: Tuple[float, float]):
        self.timelines = timelines
        self._span_start, self._span_end = span

        self._cursor = self._span_start
        self._initial_cursor = self._span_start

    def get_cursor(self) -> float:
        return self._cursor

    def get_timeline(self, timeline_id: str) -> Optional[GenericTimeline]:
        return next((timeline for timeline in self.timelines if timeline.timeline_id == timeline_id), None)

    def get_timeline_start(self, timeline: GenericTimeline) -> Optional[float]:
        if not timeline.segments:
            return None

        if any(segment is None for segment in timeline.segments):
            return None

        if self._initial_cursor is None:
            return timeline.segments[0]['start']

        return next((segment['start'] for segment in timeline.segments
                     if segment['start'] >= self._initial_cursor), None)

    def get_start(self) -> Optional[float]:
        timelines_starts = [self.get_timeline_start(timeline) for timeline in self.timelines]
        if any(timeline_start is None for timeline_start in timelines_starts):
            return None

        return min(timelines_starts)

    def _get_next_cursor(self) -> float:
        timelines_segments = [
            timeline.get_filtered_segments(
                lambda segment: segment['end'] >= self._cursor) for timeline in self.timelines]

        if any(not timeline_segments for timeline_segments in timelines_segments):
            return self._cursor

        def cut_section(timeline_segments: List[GenericFragment]) -> List[GenericFragment]:
            cut_end = 0
            index = 0
            for segment in timeline_segments:
                if segment['start'] >= self._span_end:
                    break

                index += 1
                cut_end = index

            return timeline_segments[:cut_end]

        timelines_segments = [cut_section(timeline_segments) for timeline_segments in timelines_segments]

        return min(max(segment['end'] for segment in timeline_segments) for timeline_segments in timelines_segments)

    def seek(self) -> List[Tuple[GenericTimeline, List[GenericFragment]]]:
        next_cursor = self._get_next_cursor()

        if next_cursor >= self._span_end:
            raise PlaybackFinish

        timeline_segments = []
        for timeline in self.timelines:
            filtered_segments: List[GenericFragment] = list(filter(
                lambda segment: self._cursor <= segment['start'] < next_cursor, timeline.segments))
            if filtered_segments:
                timeline_segments.append((timeline, filtered_segments))

        self._cursor = next_cursor
        return timeline_segments
