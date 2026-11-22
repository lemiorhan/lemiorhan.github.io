"""tools/sharing_sources.py against saved, unedited excerpts of what Speaker Deck
and yt-dlp return, with the network replaced. The thumbnail tests need macOS's
sips and are skipped where it is missing, as on the CI runner."""
import importlib.util
import io
import json
import os
import shutil
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test_site import ROOT, jpeg_size

spec = importlib.util.spec_from_file_location('sharing_sources', os.path.join(ROOT, 'tools', 'sharing_sources.py'))
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)

FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')
SIPS = shutil.which('sips')
LOST = 'https://files.speakerdeck.com/presentations/bf6226f515ba49d187bf1cec77543b67/preview_slide_0.jpg?27300048'
DEVOPS = 'https://files.speakerdeck.com/presentations/8b087ee13a6247c9a40adc0d1da89035/preview_slide_0.jpg?10185630'


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding='utf-8') as f:
        return f.read()


def bmp(width, height):
    row = (width * 3 + 3) // 4 * 4
    return (b'BM' + struct.pack('<IHHI', 54 + row * height, 0, 0, 54)
            + struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, row * height, 2835, 2835, 0, 0)
            + b'\x80' * (row * height))


class ReadsTheSources(unittest.TestCase):
    def test_a_speaker_deck_page_gives_each_deck_its_link_plain_title_and_cover(self):
        self.assertEqual(sources.parse_decks(fixture('speakerdeck_page.html')), [
            {'url': 'https://speakerdeck.com/lemiorhan/the-lost-chapter-rediscovering-foundations-in-software-design',
             'title': 'The Lost Chapter: Rediscovering Foundations in Software Design', 'cover': LOST},
            {'url': 'https://speakerdeck.com/lemiorhan/devops-and-technical-agility-from-theory-to-practice',
             'title': 'DevOps & Technical Agility: From Theory to Practice', 'cover': DEVOPS}])

    def test_the_decks_come_from_the_first_page_of_the_speaker_deck_account(self):
        with mock.patch.object(sources, 'fetch', return_value=fixture('speakerdeck_page.html').encode('utf-8')) as fetch:
            decks = sources.speaker_deck()
        self.assertEqual([c.args[0] for c in fetch.call_args_list], ['https://speakerdeck.com/lemiorhan'])
        self.assertEqual([d['cover'] for d in decks], [LOST, DEVOPS])

    def test_the_playlist_keeps_its_order_and_names_the_videos_no_longer_available(self):
        videos, gone = sources.parse_playlist(json.loads(fixture('playlist.json')))
        self.assertEqual(videos, [
            {'url': 'https://www.youtube.com/watch?v=EcBrbOEPclM',
             'title': 'The Rebirth of Software Craftsmanship in the AI Era_Lemi Orhan Ergin',
             'channel': 'Java Day Istanbul', 'cover': 'https://i.ytimg.com/vi/EcBrbOEPclM/hqdefault.jpg'},
            {'url': 'https://www.youtube.com/watch?v=Z8UN8VmmCxc', 'title': 'LEMİ ORHAN BUSİNESS MAGAZİNE',
             'channel': 'Business Aktuel', 'cover': 'https://i.ytimg.com/vi/Z8UN8VmmCxc/hqdefault.jpg'}])
        self.assertEqual(gone, ['Lo5METcgvq4'])

    def test_a_video_the_listing_gives_no_channel_gets_an_empty_one(self):
        videos, _ = sources.parse_playlist({'entries': [{'id': 'EcBrbOEPclM', 'title': 'Rebirth'}]})
        self.assertEqual([v['channel'] for v in videos], [''])

    def test_the_playlist_comes_from_yt_dlp_and_the_skipped_videos_are_reported(self):
        done = mock.Mock(stdout=fixture('playlist.json'))
        out = io.StringIO()
        with mock.patch.object(sources.subprocess, 'run', return_value=done) as run, redirect_stdout(out):
            videos = sources.playlist()
        self.assertEqual(run.call_args.args[0], ['yt-dlp', '--flat-playlist', '-J', sources.PLAYLIST])
        self.assertEqual([v['url'][-11:] for v in videos], ['EcBrbOEPclM', 'Z8UN8VmmCxc'])
        self.assertEqual(out.getvalue(), 'skipped, no longer available: Lo5METcgvq4\n')


class WritesTheSnapshot(unittest.TestCase):
    def test_the_snapshot_keeps_the_fields_the_build_reads(self):
        deck = {'url': 'https://speakerdeck.com/lemiorhan/a', 'title': 'A', 'cover': LOST, 'width': 480, 'height': 360}
        video = {'url': 'https://www.youtube.com/watch?v=EcBrbOEPclM', 'title': 'B', 'channel': 'C',
                 'cover': 'https://i.ytimg.com/vi/EcBrbOEPclM/hqdefault.jpg', 'width': 480, 'height': 270}
        self.assertEqual(sources.snapshot([deck], [video]), {
            'decks': [{'url': 'https://speakerdeck.com/lemiorhan/a', 'title': 'A', 'width': 480, 'height': 360}],
            'recordings': [{'url': 'https://www.youtube.com/watch?v=EcBrbOEPclM', 'title': 'B', 'channel': 'C',
                            'width': 480, 'height': 270}]})

    def test_files_no_source_item_needs_are_removed_and_named(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('kept.jpg', 'gone.jpg', 'half.jpg.part'):
                open(os.path.join(folder, name), 'wb').close()
            removed = sources.prune(folder, {os.path.join(folder, 'kept.jpg')})
            self.assertEqual((removed, os.listdir(folder)), (['gone.jpg', 'half.jpg.part'], ['kept.jpg']))

    def test_nothing_is_written_when_a_source_gives_nothing(self):
        for decks, videos in (([], [{'url': 'u'}]), ([{'url': 'u'}], [])):
            with tempfile.TemporaryDirectory() as tmp:
                sharing = os.path.join(tmp, 'sharing.json')
                with mock.patch.object(sources, 'speaker_deck', return_value=decks), \
                        mock.patch.object(sources, 'playlist', return_value=videos), \
                        mock.patch.object(sources, 'fetch') as fetch, \
                        mock.patch.object(sources, 'ROOT', tmp), mock.patch.object(sources, 'SHARING', sharing):
                    with self.assertRaises(SystemExit) as stop:
                        sources.main()
                self.assertEqual(str(stop.exception), 'found {} decks and {} recordings; nothing written, a source may '
                                                      'have changed its pages'.format(len(decks), len(videos)))
                self.assertEqual((fetch.call_count, os.listdir(tmp)), (0, []))


@unittest.skipUnless(SIPS, 'needs macOS sips')
class SavesTheThumbnails(unittest.TestCase):
    VIDEO = {'url': 'https://www.youtube.com/watch?v=EcBrbOEPclM', 'cover': 'https://i.ytimg.com/vi/EcBrbOEPclM/hqdefault.jpg'}
    DECK = {'url': 'https://speakerdeck.com/lemiorhan/the-lost-chapter', 'cover': LOST}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(sources, 'ROOT', self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def path(self, item):
        return os.path.join(self.tmp.name, sources.thumb_path(item['url']))

    def save(self, item, crop, cover):
        item = dict(item)
        with mock.patch.object(sources, 'fetch', return_value=cover) as fetch:
            new = sources.save_thumb(item, crop)
        return item, new, fetch

    def test_a_video_cover_loses_its_bars_and_a_deck_cover_keeps_its_shape_at_the_thumbnail_width(self):
        for item, crop, cover, size in ((self.VIDEO, True, bmp(480, 360), (480, 270)),
                                        (self.DECK, False, bmp(640, 480), (480, 360))):
            saved, new, fetch = self.save(item, crop, cover)
            fetch.assert_called_once_with(item['cover'])
            self.assertTrue(new)
            self.assertEqual(jpeg_size(self.path(item)), size)
            self.assertEqual((saved['width'], saved['height']), size)
            self.assertEqual(os.listdir(os.path.dirname(self.path(item))), [os.path.basename(self.path(item))])

    def test_a_thumbnail_already_saved_is_not_downloaded_again_but_its_size_is_read(self):
        self.save(self.DECK, False, bmp(1024, 576))
        saved, new, fetch = self.save(self.DECK, False, b'')
        self.assertEqual((new, fetch.call_count, saved['width'], saved['height']), (False, 0, 480, 270))

    def test_a_download_that_is_not_an_image_leaves_no_file_behind_and_is_named(self):
        for cover in (b'', b'<html>nope</html>'):
            with self.assertRaises(SystemExit) as stop:
                self.save(self.VIDEO, True, cover)
            self.assertEqual(str(stop.exception), 'assets/sharing/videos/EcBrbOEPclM.jpg from '
                                                  'https://i.ytimg.com/vi/EcBrbOEPclM/hqdefault.jpg is not an image sips can convert')
            self.assertEqual(os.listdir(os.path.dirname(self.path(self.VIDEO))), [], cover)

    def test_a_download_that_breaks_off_leaves_no_file_behind(self):
        with mock.patch.object(sources, 'fetch', side_effect=OSError('reset')):
            with self.assertRaises(OSError):
                sources.save_thumb(dict(self.VIDEO), True)
        self.assertEqual(os.listdir(os.path.dirname(self.path(self.VIDEO))), [])

    def test_a_saved_thumbnail_that_is_not_an_image_is_named(self):
        os.makedirs(os.path.dirname(self.path(self.VIDEO)))
        open(self.path(self.VIDEO), 'wb').close()
        with self.assertRaises(SystemExit) as stop:
            self.save(self.VIDEO, True, bmp(480, 360))
        self.assertEqual(str(stop.exception), 'assets/sharing/videos/EcBrbOEPclM.jpg is not an image; delete it and run this again')

    def test_a_run_saves_the_latest_thumbnails_removes_the_rest_and_writes_the_snapshot(self):
        deck = {'url': 'https://speakerdeck.com/lemiorhan/the-lost-chapter', 'title': 'The Lost Chapter', 'cover': LOST}
        older = {'url': 'https://speakerdeck.com/lemiorhan/devops', 'title': 'DevOps', 'cover': DEVOPS}
        video = {'url': 'https://www.youtube.com/watch?v=EcBrbOEPclM', 'title': 'Rebirth', 'channel': 'Java Day Istanbul',
                 'cover': 'https://i.ytimg.com/vi/EcBrbOEPclM/hqdefault.jpg'}
        later = {'url': 'https://www.youtube.com/watch?v=Z8UN8VmmCxc', 'title': 'Magazine', 'channel': 'Business Aktuel',
                 'cover': 'https://i.ytimg.com/vi/Z8UN8VmmCxc/hqdefault.jpg'}
        decks = os.path.join(self.tmp.name, 'assets', 'sharing', 'decks')
        videos = os.path.join(self.tmp.name, 'assets', 'sharing', 'videos')
        for folder, stale in ((decks, 'old-deck.jpg'), (videos, 'old-video.jpg')):
            os.makedirs(folder)
            open(os.path.join(folder, stale), 'wb').close()
        sharing = os.path.join(self.tmp.name, 'sharing.json')
        covers = {LOST: bmp(640, 480), DEVOPS: bmp(640, 480), video['cover']: bmp(480, 360), later['cover']: bmp(480, 360)}
        out = io.StringIO()
        with mock.patch.object(sources, 'speaker_deck', return_value=[deck, older]), \
                mock.patch.object(sources, 'playlist', return_value=[video, later]), \
                mock.patch.object(sources, 'fetch', side_effect=covers.get), \
                mock.patch.object(sources, 'LATEST', 1), \
                mock.patch.object(sources, 'SHARING', sharing), redirect_stdout(out):
            sources.main()
        with open(sharing, encoding='utf-8') as f:
            self.assertEqual(json.load(f), {
                'decks': [{'url': deck['url'], 'title': 'The Lost Chapter', 'width': 480, 'height': 360}],
                'recordings': [{'url': video['url'], 'title': 'Rebirth', 'channel': 'Java Day Istanbul',
                                'width': 480, 'height': 270}]})
        self.assertEqual((os.listdir(decks), os.listdir(videos)), (['the-lost-chapter.jpg'], ['EcBrbOEPclM.jpg']))
        self.assertEqual(out.getvalue(), 'removed assets/sharing/decks/old-deck.jpg\n'
                                         'removed assets/sharing/videos/old-video.jpg\n'
                                         '1 decks, 1 recordings, 2 new thumbnails\n')


if __name__ == '__main__':
    unittest.main()
