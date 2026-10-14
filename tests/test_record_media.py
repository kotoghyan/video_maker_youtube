"""Синтетический интеграционный тест установленного FFmpeg, без архива и сети."""
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave

from vinyl_codex.prepare import run
from vinyl_codex.record_prepare import verify_export


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg не установлен')
class RecordMediaTests(unittest.TestCase):
    def test_aac_start_end_and_sample_count(self):
        tool=Path(shutil.which('ffmpeg'))
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.wav'
            frames=4*44100+127
            with wave.open(str(source),'wb') as w:
                w.setparams((2,2,44100,0,'NONE','not compressed'))
                w.writeframes(b''.join(struct.pack('<hh',int(8000*math.sin(2*math.pi*440*n/44100)),
                    int(5000*math.sin(2*math.pi*330*n/44100))) for n in range(frames)))
            for name,start,duration in (('full',0,frames/44100),('fragment',1.2,1.5)):
                with self.subTest(name=name):
                    video=Path(folder)/(name+'.mp4')
                    args=['-v','error','-f','lavfi','-i','color=black:s=320x180:r=24']
                    if start:
                        args+=['-ss',str(start)]
                    args+=['-i',str(source),'-t',str(duration),'-c:v','libx264','-threads','2',
                        '-preset','ultrafast','-c:a','aac','-b:a','320k','-map_metadata','-1',str(video)]
                    run(tool,args)
                    result=verify_export(tool,video,source,duration,start)
                    self.assertEqual(result['audio_start_seconds'],0)
                    self.assertEqual(result['audio_samples'],frames if not start else round(duration*44100))
                    self.assertTrue(result['full_decode_ok'])
                    self.assertTrue(all(x['correlation']>.99 for x in result['audio_windows']))
            # Кэшированный неподвижный кадр циклически копируется в MP4.
            # B-кадры должны быть отключены, иначе DTS продлевает конец видео.
            plate=Path(folder)/'plate.mp4'
            run(tool,['-v','error','-f','lavfi','-i','color=black:s=320x180:r=24','-frames:v','24',
                '-c:v','libx264','-threads','2','-preset','veryfast','-bf','0','-g','24',str(plate)])
            output=Path(folder)/'looped.mp4'
            run(tool,['-v','error','-stream_loop','-1','-i',str(plate),'-i',str(source),
                '-t',str(frames/44100),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac',
                '-b:a','320k','-map_metadata','-1',str(output)])
            result=verify_export(tool,output,source,frames/44100)
            self.assertLessEqual(abs(result['duration_seconds']-frames/44100),1/24+.001)
