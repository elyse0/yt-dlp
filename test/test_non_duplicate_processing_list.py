import unittest

from yt_dlp.downloader.utils.processing_list import NonDuplicateProcessingList

class TestNonDuplicateProcessingList(unittest.TestCase):

    def test_empty(self):
        processing_list = NonDuplicateProcessingList()
        self.assertEqual(processing_list.seek(), None)

    def test_multiple_single_inserts(self):
        processing_list = NonDuplicateProcessingList()
        processing_list.insert('0', {'url': 'fragment-0'})
        processing_list.insert('1', {'url': 'fragment-1'})

        self.assertEqual(processing_list.seek(), {'0': {'url': 'fragment-0'}, '1': {'url': 'fragment-1'}})

    def test_multiple_many_inserts(self):
        processing_list = NonDuplicateProcessingList()
        processing_list.insert_many({'0': {'url': 'fragment-0'}, '1': {'url': 'fragment-1'}})
        processing_list.insert_many({'2': {'url': 'fragment-2'}, '3': {'url': 'fragment-3'}})

        self.assertEqual(processing_list.seek(), {
            '0': {'url': 'fragment-0'},
            '1': {'url': 'fragment-1'},
            '2': {'url': 'fragment-2'},
            '3': {'url': 'fragment-3'},
        })

    def test_multiple_seek_requests(self):
        processing_list = NonDuplicateProcessingList()
        processing_list.insert('0', {'url': 'fragment-0'})
        processing_list.insert('1', {'url': 'fragment-1'})

        self.assertEqual(processing_list.seek(), {'0': {'url': 'fragment-0'}, '1': {'url': 'fragment-1'}})
        self.assertEqual(processing_list.seek(), None)

        processing_list.insert('1', {'url': 'fragment-1'})
        processing_list.insert('2', {'url': 'fragment-2'})
        self.assertEqual(processing_list.seek(), {'2': {'url': 'fragment-2'}})
        self.assertEqual(processing_list.seek(), None)


if __name__ == '__main__':
    unittest.main()
