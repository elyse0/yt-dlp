import math

from abc import abstractmethod
from typing import Generic, List, Optional, TypedDict, TypeVar


class BaseFragment(TypedDict):
    start: Optional[float]
    end: Optional[float]


GenericFragment = TypeVar('GenericFragment', bound=BaseFragment)


class Timeline(Generic[GenericFragment]):
    def __init__(self, timeline_id: str, filepath: str):
        self.timeline_id = timeline_id
        self.filepath = filepath
        self.segments: List[GenericFragment] = []

    def get_filtered_segments(self, filter_func) -> List[GenericFragment]:
        return list(filter(filter_func, self.segments))

    @abstractmethod
    def insert_one(self, new_segment: GenericFragment) -> None:
        pass

    def insert_many(self, segments: List[GenericFragment]):
        for segment in segments:
            self.insert_one(segment)


class HlsTimeline(Timeline[GenericFragment]):

    def __init__(self, timeline_id: str, filepath: str, manifest_url: str, fragments_and_stats_func):
        super().__init__(timeline_id, filepath)
        self.manifest_url = manifest_url
        self.fragments_and_stats_func = fragments_and_stats_func

    def get_manifest_fragments_and_stats(self):
        return self.fragments_and_stats_func(self.manifest_url)

    def all_segments_have_real_time(self) -> bool:
        return all(segment.get('automatic_time') is False for segment in self.segments)

    def insert_one(self, new_segment: GenericFragment) -> None:
        if not len(self.segments):
            self.segments.append(new_segment)
            return

        last_segment = self.segments[-1]
        media_sequence_difference = last_segment['media_sequence'] - new_segment['media_sequence']
        if media_sequence_difference >= 0:
            return

        if media_sequence_difference < -1:
            print('Non continuous media sequence')

        if media_sequence_difference == -1:
            self.segments.append({
                **new_segment,
                'start': last_segment['end'],
                'end': last_segment['end'] + new_segment['duration'],
            })
            return

        self.segments.append(new_segment)


class DashTimeline(Timeline[GenericFragment]):

    def __init__(self, timeline_id: str, filepath: str, base_url: str):
        super().__init__(timeline_id, filepath)
        self.base_url = base_url

    def insert_one(self, new_segment: GenericFragment) -> None:
        if new_segment.get('start') is None or new_segment.get('end') is None:
            return

        if not len(self.segments):
            self.segments.append(new_segment)
            return

        tolerance = 0.1
        last_segment = self.segments[-1]
        if last_segment['end'] - tolerance > new_segment['start']:
            return

        if math.isclose(last_segment['end'], new_segment['start'], abs_tol=tolerance, rel_tol=0):
            self.segments.append({
                **new_segment,
                'start': last_segment['end'],
                'end': new_segment['end'],
            })
            return

        print('Non continuous fragment, this may result in out of sync formats')
        self.segments.append(new_segment)
