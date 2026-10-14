from pathlib import Path
import hashlib
import json
import tempfile
import unittest
import wave

from vinyl_codex.config import Config
from vinyl_codex.metadata import RELEASE_STRINGS, TRACK_FIELDS, read_metadata
from vinyl_codex.record_prepare import join_pcm, fragment_options, recipe_plan, public_text_guard, texts
from vinyl_codex.safety import SafeError


class RecordPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.archive, self.work = root/'archive', root/'work'
        self.archive.mkdir()
        self.work.mkdir()
        self.config = Config(self.archive,self.work)
        self.record = self.archive/'900001 - Synthetic'
        for folder in ('IMAGES','TRACKS','METADATA'):
            (self.record/folder).mkdir(parents=True)
        self.track = {key:'Unknown' for key in TRACK_FIELDS}
        self.track.update(disc='D01',side='A',track='01',work='Synthetic',performer='Singer',
                          file_name='900001_D01_A01 - Synthetic.wav')
        self.metadata={key:'Unknown' for key in RELEASE_STRINGS}
        self.metadata.update(museum_id='900001',number_of_discs=1,tracks=[self.track])
        (self.record/'METADATA'/'metadata.json').write_text(json.dumps(self.metadata),encoding='utf-8')
        self.audio=self.record/'TRACKS'/self.track['file_name']
        self.wav(self.audio,b'\x01\x02'*5)
        for name in ('front.jpg','back.jpg','a.jpg','b.jpg'):
            (self.record/'IMAGES'/name).write_bytes(b'synthetic')
        self.recipe=dict(museum_id='900001',record=str(self.record),metadata_name='metadata.json',
                         selection='both',version='draft-v1',image_roles_reviewed=True,
                         images=dict(front='front.jpg',back='back.jpg',D01_A='a.jpg',D01_B='b.jpg'))
        self.recipe_path=self.work/'recipe.json'
        self.save()

    def save(self):
        self.recipe_path.write_text(json.dumps(self.recipe),encoding='utf-8')

    def wav(self,path,pcm,rate=44100):
        with wave.open(str(path),'wb') as w:
            w.setparams((1,2,rate,0,'NONE','not compressed'))
            w.writeframes(pcm)

    def test_explicit_metadata_filename_readonly(self):
        before=hashlib.sha256((self.record/'METADATA'/'metadata.json').read_bytes()).digest()
        data=read_metadata(self.record,'900001','metadata.json')
        self.assertEqual(data['museum_id'],'900001')
        self.assertEqual(before,hashlib.sha256((self.record/'METADATA'/'metadata.json').read_bytes()).digest())
        self.assertEqual(list(self.work.iterdir()),[self.recipe_path])

    def test_metadata_traversal_rejected(self):
        with self.assertRaises(SafeError):
            read_metadata(self.record,'900001','../metadata.json')

    def test_pcm_join_preserves_samples_and_order(self):
        other=self.work/'b.wav'
        self.wav(other,b'\x03\x04'*7)
        output=self.work/'joined.wav'
        info=join_pcm([self.audio,other],output)
        self.assertEqual(info['frames'],12)
        with wave.open(str(output),'rb') as w:
            self.assertEqual(w.readframes(12),b'\x01\x02'*5+b'\x03\x04'*7)

    def test_mismatched_pcm_rejected_before_write(self):
        other=self.work/'b.wav'
        self.wav(other,b'\x03\x04',48000)
        output=self.work/'joined.wav'
        with self.assertRaises(SafeError):
            join_pcm([self.audio,other],output)
        self.assertFalse(output.exists())

    def test_no_overwrite_pcm(self):
        with self.assertRaises(SafeError):
            join_pcm([self.audio],self.audio)

    def test_fragment_boundaries(self):
        for duration in (31,124.9,346.35):
            for _,start,length in fragment_options(duration):
                self.assertGreaterEqual(start,0)
                self.assertLessEqual(start+length,duration+.001)

    def test_public_id_guard(self):
        for text in ('Museum ID: 900001','example 900001','Թանգարանային ID'):
            with self.assertRaises(SafeError):
                public_text_guard(text,'900001')
        public_text_guard(texts(self.metadata,[self.track]),'900001')

    def test_recipe_is_readonly_and_requires_photo_review(self):
        recipe_plan(self.config,self.recipe_path)
        self.assertEqual(list(self.work.iterdir()),[self.recipe_path])
        self.recipe['image_roles_reviewed']=False
        self.save()
        with self.assertRaises(SafeError):
            recipe_plan(self.config,self.recipe_path)

    def test_video_blocks_photo_fallback(self):
        (self.record/'VIDEO').mkdir()
        (self.record/'VIDEO'/'source.mp4').write_bytes(b'synthetic video')
        with self.assertRaises(SafeError):
            recipe_plan(self.config,self.recipe_path)

    def test_movements_are_not_split(self):
        self.metadata['tracks'][0]['movement']='I Allegro'
        (self.record/'METADATA'/'metadata.json').write_text(json.dumps(self.metadata))
        with self.assertRaises(SafeError):
            recipe_plan(self.config,self.recipe_path)

    def test_unlisted_track_rejected(self):
        (self.record/'TRACKS'/'extra.wav').write_bytes(b'extra')
        with self.assertRaises(SafeError):
            recipe_plan(self.config,self.recipe_path)

    def test_wrong_id_rejected(self):
        self.recipe['museum_id']='1'
        self.save()
        with self.assertRaises(SafeError):
            recipe_plan(self.config,self.recipe_path)


if __name__=='__main__':
    unittest.main()
