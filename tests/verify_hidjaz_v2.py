"""Ручной интеграционный запуск: только чтение архива, отчёт в WORK_ROOT."""
import array
import json
import math
from pathlib import Path
import re
import subprocess
import sys

from vinyl_codex.config import load_config
from vinyl_codex.inventory import dry_run
from vinyl_codex.prepare import atomic_json, checksum, probe, run
from vinyl_codex.safety import local_file, output_path


def verify(ffmpeg):
    config = load_config('config.json')
    tool = Path(ffmpeg)
    prober = tool.with_name('ffprobe.exe')
    record = config.archive / 'Armenian' / '246 - Varoujan Kevorkian - Danzas Armenias'
    target = config.work / '246' / 'D01_A01' / 'draft-v2'
    previous = target.with_name('draft-v1')
    baseline = json.loads(Path('docs/v2-preservation-baseline.json').read_text(encoding='utf-8'))
    actual_paths = {str(p) for root in (record, previous) for p in root.rglob('*') if p.is_file()}
    assert actual_paths == set(baseline), 'Изменился набор архивных файлов или файлов v1'
    for name, expected in baseline.items():
        path = local_file(Path(name), config.archive if Path(name).is_relative_to(record) else config.work)
        assert checksum(path) == expected['sha256']
        assert path.stat().st_size == expected['bytes']
        assert path.stat().st_mtime_ns == expected['mtime_ns']
    discovery = dry_run(config, '246', str(record), 'approved-246')
    assert discovery['track_count'] == 12
    state = json.loads((target / 'state.json').read_text(encoding='utf-8'))
    assert state['museum_id'] == '246' and state['publication_approval'] is None
    public = (target / 'captions-hy-en.md').read_text(encoding='utf-8')
    assert not re.search(r'(?i)museum\s*id|թանգարանային\s*id|(?<!\d)246(?!\d)', public)
    assert not any(p.name.startswith(('intro', 'outro')) for p in target.iterdir())
    video = local_file(target / 'youtube-full-draft-v2.mp4', config.work)
    source = local_file(target / 'source-audio.wav', config.work)
    info = probe(prober, video)
    audio_stream = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert float(audio_stream['start_time']) == 0
    duration = state['source_duration_seconds']
    assert abs(float(info['format']['duration']) - duration) < 1 / 24
    for entry in state['outputs']:
        export = local_file(target / entry['file'], config.work)
        run(tool, ['-v', 'error', '-xerror', '-i', str(export), '-f', 'null', '-'])
        tags = probe(prober, export)
        public_tags = json.dumps([tags['format'].get('tags', {}), *[s.get('tags', {}) for s in tags['streams']]])
        assert '246' not in public_tags and 'Museum ID' not in public_tags
    def pcm(path, start=None):
        args = [str(tool), '-nostdin', '-v', 'error', '-i', str(path)]
        if start is not None:
            args += ['-ss', str(start), '-t', '1']
        result = subprocess.run(args + ['-map', '0:a:0', '-ac', '1', '-ar', '44100', '-f', 'f32le', '-'],
                                capture_output=True, check=True, timeout=120)
        return result.stdout
    source_samples, output_samples = len(pcm(source)) // 4, len(pcm(video)) // 4
    assert output_samples >= source_samples
    assert output_samples - source_samples <= 1024, 'Звук обрезан или добавлена тишина'
    windows = []
    for start in (0, 150, duration - 1):
        a, b = array.array('f'), array.array('f')
        a.frombytes(pcm(source, start)); b.frombytes(pcm(video, start))
        n = min(len(a), len(b)); a = a[:n]; b = b[:n]
        mean_a, mean_b = sum(a) / n, sum(b) / n
        covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        correlation = covariance / math.sqrt(sum((x - mean_a)**2 for x in a) * sum((y - mean_b)**2 for y in b))
        assert correlation > 0.99, f'Звук смещён или изменён: {start}'
        windows.append(dict(source_start_seconds=start, export_start_seconds=start, correlation=correlation))
    for label, start in [('start', 0), ('end', duration - 1 / 24)]:
        image = output_path(target / f'preview-{label}.png', config.archive, config.work)
        run(tool, ['-v', 'error', '-ss', str(start), '-i', str(video), '-frames:v', '1', str(image)])
    result = dict(status='passed', archive_and_v1_files_unchanged=len(baseline),
                  internal_id_discovery_ok=True, public_text_and_container_tags_without_id=True,
                  audio_start_seconds=0, source_duration_seconds=duration,
                  export_duration_seconds=float(info['format']['duration']),
                  source_samples=source_samples, decoded_export_samples=output_samples,
                  aac_padding_samples=output_samples-source_samples, waveform_windows=windows,
                  all_exports_full_decode_ok=True, uploads=0, publication_approval=None)
    atomic_json(config, target / 'verification-v2.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    verify(sys.argv[1])
