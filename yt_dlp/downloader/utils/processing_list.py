from typing import Any, Dict, Union


class NonDuplicateProcessingList:
    def __init__(self):
        self.processing_list = {}
        self.head_key = None

    def _exists(self, key: str):
        return key in self.processing_list.keys()

    def insert(self, key: str, value: Any) -> None:
        if self._exists(key):
            return

        self.processing_list[key] = value

    def insert_many(self, new_items: Dict[str, Any]) -> None:
        for key in new_items.keys():
            self.insert(key, new_items[key])

    def seek(self) -> Union[Dict[str, Any], None]:
        processing_list_keys = list(self.processing_list.keys())
        if not len(processing_list_keys):
            return None

        if self.head_key is None:
            self.head_key = processing_list_keys[-1]
            return self.processing_list

        head_key_index = processing_list_keys.index(self.head_key)
        seek_list_keys = processing_list_keys[head_key_index + 1:]
        if not len(seek_list_keys):
            return None

        seek_list: Dict[str, Any] = {}
        for key in seek_list_keys:
            seek_list[key] = self.processing_list[key]

        self.head_key = seek_list_keys[-1]
        return seek_list
